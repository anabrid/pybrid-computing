#!/usr/bin/env python3

# Copyright (c) 2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
LucipyWrapper: High-level interface for LUCIDAC analog computers.

This module provides the LucipyWrapper class, which manages one or more LUCIDAC
devices via a single controller.

Single-device workflow:
    >>> luci = LucipyWrapper("tcp://192.168.1.100:5732")
    >>> circuit = Circuit()
    >>> # ... build circuit ...
    >>> luci.set_circuit(circuit)
    >>> luci.set_daq(sample_rate=1000)
    >>> luci.set_run(ic_time={"value": 100_000, "prefix": "NANO"},
    ...              op_time={"value": 10_000_000, "prefix": "NANO"})
    >>> run = luci.run()
"""

import asyncio
import copy
import logging
import os
import urllib.parse
from ipaddress import ip_network
from typing import Optional

import pybrid.base.proto.main_pb2 as pb
from pybrid.base.utils.addressing import Addressing
from pybrid.lucidac.controller import Controller as LUCIStackController
from pybrid.lucipy.circuits import Circuit
from pybrid.redac import DAQConfig, RunConfig, Run
from pybrid.redac.detect import detect_in_network

logger = logging.getLogger(__name__)


class LucipyWrapper:
    """
    High-level interface for LUCIDAC analog computer(s).

    Uses a single controller for all devices, leveraging the REDAC
    controller's distributed run machinery for multi-device sync and
    data aggregation.

    A LucipyWrapper can be either a *root* (created via ``__init__``) or a
    *view* (created via ``__getitem__``). Views share the parent's controller,
    endpoints, and circuits dict (writes are visible across all views and root).
    """

    ENDPOINT_ENV_NAME = "LUCIDAC_ENDPOINT"
    default_port = 5732

    def __init__(self, *hosts: str, with_proxy: bool = False):
        """Initialize LucipyWrapper with one or more endpoints.

        Args:
            *hosts: Endpoint strings (e.g., "tcp://host:port", "host:port",
                    or bare "host"). If not provided, checks LUCIDAC_ENDPOINT
                    environment variable, then attempts auto-detection.
            with_proxy: Deprecated. Enable proxy mode (single endpoint,
                        discovers multiple devices behind a proxy).
        """
        # === Shared state (views hold references to the same objects) ===
        self._controller: Optional[LUCIStackController] = None
        self._endpoints: list[tuple[str, int]] = []
        self._circuits: dict[int, Circuit] = {}

        # === Per-instance state ===
        self._daq_config = DAQConfig()
        self._run_config = RunConfig()
        self._is_view: bool = False
        self._device_indices: list[int] = []

        if with_proxy:
            self._init_proxy_mode(*hosts)
        else:
            self._init_direct_mode(*hosts)

        # Device indices: root stacks include all devices
        self._device_indices = list(range(self._num_devices))

    def _init_direct_mode(self, *hosts: str) -> None:
        """Initialize in direct mode (one endpoint per device).

        Each host string maps to one device in the pool and the endpoint list.

        Args:
            *hosts: Endpoint strings (e.g., "tcp://host:port").
        """
        endpoints = self._resolve_endpoints(*hosts)

        for idx, endpoint in enumerate(endpoints):
            host, port = self._parse_endpoint(endpoint)
            self._endpoints.append((host, port))

        self._num_devices = len(endpoints)

    def _init_proxy_mode(self, *hosts: str) -> None:
        """Initialize in proxy mode (single endpoint, multiple devices behind proxy).

        Connects to a single proxy endpoint with ``standalone=False`` on the
        controller, discovers devices behind the proxy, and registers each
        using the actual discovered MAC addresses.

        Args:
            *hosts: Must contain exactly one endpoint string.

        Raises:
            ValueError: If not exactly one endpoint is provided.
        """
        if len(hosts) != 1:
            raise ValueError(
                "Proxy mode requires exactly one endpoint, "
                f"got {len(hosts)}"
            )

        host, port = self._parse_endpoint(hosts[0])

        try:
            asyncio.get_running_loop()
            raise ValueError(
                "Proxy mode initialization cannot be performed from an "
                "async context. Please initialize LUCIStack outside of "
                "an async function."
            )
        except RuntimeError:
            device_macs = asyncio.run(
                self._discover_proxy_devices(host, port)
            )

        if len(device_macs) == 0:
            raise ValueError(
                f"No devices found behind proxy at {host}:{port}"
            )

        logger.info(
            f"Proxy mode: discovered {len(device_macs)} device(s) at "
            f"{host}:{port}"
        )

        for idx, mac in enumerate(device_macs):
            self._endpoints.append((host, port))

        self._num_devices = len(device_macs)

    async def _discover_proxy_devices(
        self, host: str, port: int
    ) -> list[str]:
        """Connect to a proxy endpoint and discover devices behind it.

        Creates a temporary controller with ``standalone=False``, connects
        to the proxy, and returns the list of virtual MAC addresses for
        all carriers the proxy exposes.

        Args:
            host: Proxy host address.
            port: Proxy TCP port.

        Returns:
            List of virtual MAC address strings for discovered carriers.
        """
        controller = LUCIStackController(standalone=False)
        try:
            await controller.add_device(host, port)
            device_macs = [
                str(path) for path in controller.devices.keys()
            ]
            return device_macs
        finally:
            await controller.stop()

    @classmethod
    def _create_view(cls, parent: "LucipyWrapper", device_indices: list[int]) -> "LucipyWrapper":
        """Create a lightweight view sharing the parent's shared state.

        Args:
            parent: Root LucipyWrapper whose shared state to reference.
            device_indices: Device indices this view operates on.

        Returns:
            A new LucipyWrapper marked as a view.
        """
        view = object.__new__(cls)
        # Shared: same references as parent (not copies!)
        view._controller = parent._controller
        view._endpoints = parent._endpoints
        view._circuits = parent._circuits
        # Per-instance: scoped to this view
        view._daq_config = copy.deepcopy(parent._daq_config)
        view._run_config = copy.deepcopy(parent._run_config)
        view._is_view = True
        view._device_indices = device_indices
        view._num_devices = len(device_indices)
        return view

    def __getitem__(self, key) -> "LucipyWrapper":
        """Create a view over a subset of carriers.

        Args:
            key: Device index (int), tuple of indices, or slice.

        Returns:
            A new LucipyWrapper view instance.

        Raises:
            IndexError: If any device index is out of range.
            TypeError: If key type is not supported.
        """
        num_indices = len(self._device_indices)
        if isinstance(key, int):
            if key < 0 or key >= num_indices:
                raise IndexError(f"Device index {key} out of range (0..{num_indices - 1})")
            device_indices = [self._device_indices[key]]
        elif isinstance(key, tuple):
            for k in key:
                if k < 0 or k >= num_indices:
                    raise IndexError(f"Device index {k} out of range (0..{num_indices - 1})")
            device_indices = [self._device_indices[k] for k in key]
        elif isinstance(key, slice):
            device_indices = self._device_indices[key]
        else:
            raise TypeError(f"Unsupported key type {type(key).__name__}")
        return LucipyWrapper._create_view(self, device_indices)

    def set_circuit(self, circuit: Circuit) -> None:
        """Store circuit for all devices in this view's scope.

        Deep-copies the circuit to prevent external modifications.
        Writes into the shared _circuits dict, so the root wrapper
        (and other views) see this assignment at run() time.

        Args:
            circuit: Circuit instance to execute.
        """
        for idx in self._device_indices:
            self._circuits[idx] = copy.deepcopy(circuit)

    def set_daq(self, **kwargs) -> None:
        """Configure DAQ (Data Acquisition) parameters.

        Args:
            **kwargs: DAQ configuration parameters passed to DAQConfig.
        """
        self._daq_config = DAQConfig(**kwargs)

    def set_run(self, **kwargs) -> None:
        """Configure run parameters.

        Args:
            **kwargs: Run configuration parameters passed to RunConfig.
        """
        self._run_config = RunConfig(**kwargs)

    def run(self) -> Run:
        """Execute the computation and return results.

        Synchronous wrapper around the async _run() method.

        Returns:
            A single Run object with execution results.

        Raises:
            RuntimeError: If no circuit has been set or if called from async context.
        """
        try:
            asyncio.get_running_loop()
            raise RuntimeError(
                "run() cannot be called from an async context. "
                "Use 'await luci._run()' instead."
            )
        except RuntimeError as e:
            if "no running event loop" in str(e):
                return asyncio.run(self._run())
            raise

    async def _run(self) -> Run:
        """Execute computation (async implementation).

        Returns:
            Run object with execution results.

        Raises:
            RuntimeError: If no circuit has been set for any device in scope,
                or if called on a view before the root is initialized.
        """
        if self._is_view and self._controller is None:
            raise RuntimeError(
                "Cannot run from a view before the root wrapper has been "
                "initialized. Call 'await root._ensure_controller()' or "
                "'root.run()' first."
            )

        await self._ensure_controller()

        # Build merged config bundle from all circuits
        all_configs = []
        for idx in self._device_indices:
            circuit = self._circuits.get(idx)
            if circuit is None:
                raise RuntimeError(f"No circuit set for device {idx}!")

            _, pb_file = circuit.to_config()
            carrier_mac = self._controller.computer.carriers[idx].path.to_mac()
            translated = Addressing.remap_virtual_mac(pb_file, carrier_mac)
            all_configs.extend(translated.bundle.configs)

        # Deduce num_channels from first circuit's ADC assignments
        first_circuit = self._circuits[self._device_indices[0]]
        daq_config = copy.deepcopy(self._daq_config)
        if daq_config.num_channels == 0:
            num_channels = self._count_adc_channels(first_circuit)
            if num_channels > 0:
                daq_config.num_channels = num_channels

        # Send merged config to controller
        await self._controller.forward_set_config(
            pb.ConfigCommand(bundle=pb.ConfigBundle(configs=all_configs))
        )

        # Execute run
        run_class = self._controller.get_run_implementation()
        executable_run = await self._controller.start_and_await_run(
            run_class(config=self._run_config, daq=daq_config)
        )

        return executable_run

    async def _ensure_controller(self):
        """Lazy init: create controller, add all devices, detect standalone mode.

        This is idempotent -- subsequent calls are no-ops if the controller
        is already initialized.

        Raises:
            RuntimeError: If called on a view instead of the root wrapper.
        """
        if self._is_view:
            raise RuntimeError(
                "_ensure_controller() must be called on the root wrapper, "
                "not on a view. Call it on the parent LucipyWrapper first."
            )

        if self._controller is not None:
            return

        self._controller = LUCIStackController(standalone=True)

        for host, port in self._endpoints:
            await self._controller.add_device(host, port)

        # Post-add standalone detection:
        # If any single protocol manages multiple carriers -> proxy mode
        for protocol, managed_paths in self._controller.protocols.items():
            if len(managed_paths) > 1:
                self._controller.standalone = False
                break

        # Update device_indices from actual discovered carriers
        self._device_indices = list(range(len(self._controller.computer.carriers)))

        await self._controller.reset()
        self._print_discovery_summary()

    async def close(self):
        """Shutdown controller, release TCP/UDP connections."""
        if self._controller is not None:
            await self._controller.stop()
            self._controller = None

    def _resolve_endpoints(self, *hosts: str) -> list[str]:
        """Resolve endpoints with fallback logic.

        If no hosts provided:
        1. Check LUCIDAC_ENDPOINT environment variable
        2. Attempt mDNS auto-detection (sync context only)
        3. Raise ValueError if nothing found

        Auto-detection uses Zeroconf/mDNS to discover all LUCIDAC devices
        on the local network. All discovered devices are returned as
        endpoints, enabling multi-device setups without manual configuration.

        Args:
            *hosts: Endpoint strings (may be empty).

        Returns:
            List of endpoint strings.

        Raises:
            ValueError: If no endpoints can be determined, or if
                auto-detection is attempted from an async context.
        """
        if len(hosts) > 0:
            return list(hosts)

        if self.ENDPOINT_ENV_NAME in os.environ:
            endpoint = os.environ[self.ENDPOINT_ENV_NAME]
            logger.info(f"Using endpoint from {self.ENDPOINT_ENV_NAME}: {endpoint}")
            return [endpoint]

        logger.info(
            f"No endpoint specified and {self.ENDPOINT_ENV_NAME} not set. "
            "Attempting mDNS auto-detection..."
        )

        # Auto-detection requires asyncio.run(), which cannot be called
        # from within an already-running event loop.
        try:
            asyncio.get_running_loop()
            raise ValueError(
                "Auto-detection failed: cannot run mDNS discovery from an "
                "async context. Please provide an endpoint explicitly, set "
                f"the {self.ENDPOINT_ENV_NAME} environment variable, or "
                "initialize LucipyWrapper outside of an async function."
            )
        except RuntimeError:
            # No running event loop — safe to use asyncio.run().
            pass

        try:
            devices = asyncio.run(
                detect_in_network(ip_network("0.0.0.0/0"))
            )
        except (asyncio.TimeoutError, RuntimeError) as e:
            raise ValueError(
                f"No LUCIDAC found via auto-detection ({e}). Please provide "
                f"an endpoint explicitly or set {self.ENDPOINT_ENV_NAME} "
                "environment variable."
            ) from e

        if len(devices) == 0:
            raise ValueError(
                "No LUCIDAC found via auto-detection. Please provide an "
                f"endpoint explicitly or set {self.ENDPOINT_ENV_NAME} "
                "environment variable."
            )

        endpoints = []
        for host, port, name in devices:
            endpoint = f"tcp://{host}:{port}"
            logger.info(f"Auto-detected LUCIDAC: {endpoint} ({name})")
            endpoints.append(endpoint)

        logger.info(f"Auto-detected {len(endpoints)} LUCIDAC device(s)")
        return endpoints

    def _parse_endpoint(self, endpoint: str) -> tuple[str, int]:
        """Parse endpoint string to extract host and port.

        Accepts: ``tcp://host:port``, ``host:port``, ``host``

        Args:
            endpoint: Endpoint string.

        Returns:
            Tuple of (host, port).

        Raises:
            ValueError: If endpoint format is invalid.
        """
        if "://" not in endpoint:
            endpoint = f"tcp://{endpoint}"

        url = urllib.parse.urlparse(endpoint)
        host = (url.hostname or "") + (url.path or "")
        if not host:
            raise ValueError(f"Invalid endpoint '{endpoint}': no host found")

        port = int(url.port or self.default_port)
        return host, port

    def _count_adc_channels(self, circuit: Circuit) -> int:
        """Count the number of ADC channels assigned in the circuit.

        Args:
            circuit: Circuit instance.

        Returns:
            Number of assigned ADC channels.
        """
        return len([ch for ch in circuit._adc_channels if ch is not None])

    def _print_discovery_summary(self):
        """Print a summary of discovered devices to stdout."""
        carriers = self._controller.computer.carriers
        num = len(carriers)
        mode = "standalone" if self._controller.standalone else "proxy"
        print(f"LUCIDAC stack -- {num} device(s), mode={mode}")
        for i, carrier in enumerate(carriers):
            mac = carrier.path.to_mac()
            prefix = "(*)" if i == 0 else "   "
            suffix = " (sync master)" if i == 0 else ""
            print(f"  {prefix} {mac}{suffix}")

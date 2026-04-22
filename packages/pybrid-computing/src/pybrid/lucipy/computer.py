#!/usr/bin/env python3

# Copyright (c) 2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
LucipyWrapper: High-level interface for LUCIDAC analog computers.

This module provides the LucipyWrapper class, which manages one or more LUCIDAC
devices via a single controller.

Endpoints can be direct (one per device) or a single proxy endpoint that
aggregates multiple devices.  Topology detection is handled automatically
by the underlying :class:`~pybrid.redac.connection.ConnectionManager`.

Single-device workflow:
    >>> luci = LucipyWrapper("tcp://192.168.1.100:5732")
    >>> c = luci.create_circuit()
    >>> # ... build circuit ...
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
import warnings
from ipaddress import ip_network
from typing import Optional

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

    Circuits are created via :meth:`create_circuit`, which discovers the
    physical MAC address and automatically registers the circuit for the
    given device.  The circuit is stored by reference — mutations after
    creation are picked up at :meth:`run` time.
    """

    ENDPOINT_ENV_NAME = "LUCIDAC_ENDPOINT"
    default_port = 5732

    def __init__(self, *hosts: str, **kwargs):
        """Initialize LucipyWrapper with one or more endpoints.

        Pass one endpoint per direct device, or a single proxy endpoint
        (the controller discovers all carriers behind it automatically).

        Args:
            *hosts: Endpoint strings (e.g., "tcp://host:port", "host:port",
                    or bare "host"). If not provided, checks LUCIDAC_ENDPOINT
                    environment variable, then attempts auto-detection.
            **kwargs: Accepted for backward compatibility.  ``with_proxy``
                is deprecated and ignored (proxy detection is automatic).
        """
        if "with_proxy" in kwargs:
            warnings.warn(
                "The 'with_proxy' parameter is deprecated and ignored. "
                "Proxy detection is now automatic via the ConnectionManager.",
                DeprecationWarning,
                stacklevel=2,
            )

        self._controller: Optional[LUCIStackController] = None
        self._endpoints: list[tuple[str, int]] = []
        self._circuits: dict[int, Circuit] = {}
        self._daq_config = DAQConfig()
        self._run_config = RunConfig()
        self._device_indices: list[int] = []

        endpoints = self._resolve_endpoints(*hosts)
        for endpoint in endpoints:
            host, port = self._parse_endpoint(endpoint)
            self._endpoints.append((host, port))

        self._num_devices = len(endpoints)
        self._device_indices = list(range(self._num_devices))

    def controller(self):
        return self._controller

    def create_circuit(self, device_index: int | None = None) -> Circuit:
        """Create a Circuit scoped to a specific carrier's MAC address.

        The returned circuit is stored by reference for the given device
        index — mutations after creation are picked up at :meth:`run` time.
        Calling ``create_circuit`` again for the same device replaces the
        previous circuit.

        If no ``device_index`` is given, defaults to device 0.

        :param device_index: Index of the carrier (0-based), or None to
            default to device 0.
        :returns: A new Circuit with the carrier's physical MAC.
        :raises IndexError: If ``device_index`` is out of range.
        """
        # Eagerly initialise controller if not yet done
        if self._controller is None:
            try:
                asyncio.get_running_loop()
                raise RuntimeError(
                    "create_circuit() requires the controller to be initialised. "
                    "Use 'await luci._ensure_controller()' first in async contexts."
                )
            except RuntimeError as e:
                if "no running event loop" in str(e):
                    asyncio.run(self._ensure_controller())
                else:
                    raise

        carriers = self._controller.computer.carriers

        if device_index is None:
            if len(carriers) > 1:
                logger.info(
                    "Multiple devices discovered; defaulting to device 0. "
                    "Pass device_index explicitly to target a different device."
                )
            device_index = 0

        if device_index < 0 or device_index >= len(carriers):
            raise IndexError(
                f"device_index {device_index} out of range "
                f"(0..{len(carriers) - 1})"
            )

        mac = carriers[device_index].path.to_mac()
        circuit = Circuit(mac)
        self._circuits[device_index] = circuit
        return circuit

    def set_circuit(self, circuit: Circuit) -> None:
        """Store a circuit for all devices.

        Deep-copies the circuit to each device slot.  Prefer
        :meth:`create_circuit` which automatically discovers the
        physical MAC and stores the circuit by reference.

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

        Builds a :class:`~pybrid.redac.session.Session` pipeline that uploads
        the merged config module and then runs the computation.

        Returns:
            Run object with execution results.

        Raises:
            RuntimeError: If no circuit has been set for any device in scope.
        """
        await self._ensure_controller()

        # Deduce num_channels from first circuit's ADC assignments
        first_circuit = self._circuits[self._device_indices[0]]
        daq_config = copy.deepcopy(self._daq_config)
        if daq_config.num_channels == 0:
            num_channels = self._count_adc_channels(first_circuit)
            if num_channels > 0:
                daq_config.num_channels = num_channels

        # Build and execute session pipeline
        session = self._controller.create_session()
        for idx in self._device_indices:
            circuit = self._circuits.get(idx)
            if circuit is None:
                raise RuntimeError(f"No circuit set for device {idx}!")
            session.set_config(circuit._lucidac)
        session.calibrate(gain=True, offset=True)
        session.run(config=self._run_config, daq=daq_config)
        runs = await session.execute()

        return runs[0] if runs else None

    async def _ensure_controller(self):
        """Lazy init: create controller, add all devices.

        This is idempotent -- subsequent calls are no-ops if the controller
        is already initialized.

        The :class:`~pybrid.redac.connection.ConnectionManager` handles
        topology detection (direct vs proxy) automatically when devices
        are added.
        """
        if self._controller is not None:
            return

        self._controller = LUCIStackController()

        for host, port in self._endpoints:
            await self._controller.add_device(host, port)

        # Update device_indices from actual discovered carriers
        # (a proxy endpoint may expose more carriers than endpoints given)
        self._device_indices = list(range(len(self._controller.computer.carriers)))

        # Pre-populate empty default circuits for devices that don't have one yet.
        # This allows running a multi-device setup where the user only programs
        # a subset of devices — unprogrammed devices get a no-op circuit.
        carriers = self._controller.computer.carriers
        for idx in self._device_indices:
            if idx not in self._circuits:
                mac = carriers[idx].path.to_mac()
                self._circuits[idx] = Circuit(mac)

        await self._controller.reset()
        self._print_discovery_summary()

    async def close(self):
        """Shutdown controller, release TCP/UDP connections."""
        if self._controller is not None:
            await self._controller.stop()
            self._controller = None

    def __del__(self):
        """Clean up connections on garbage collection.

        Calls the native C++ stop() directly on each connection, bypassing
        the async layer (whose executor may already be shut down at
        interpreter exit).  This ensures the proxy sees a clean TCP
        disconnect instead of waiting for a stale socket timeout.
        """
        if self._controller is None:
            return
        try:
            cm = self._controller.connection_manager
            for conn in cm.get_unique_connections():
                try:
                    if hasattr(conn, "data") and conn.data is not None:
                        conn.data.stop()
                    if hasattr(conn, "control") and conn.control is not None:
                        conn.control._native.stop()
                except Exception:
                    pass
            cm.connections.clear()
        except Exception:
            pass
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
        return len([ch for ch in circuit._carrier.adc_config if ch is not None])

    def _print_discovery_summary(self):
        """Print a summary of discovered devices to stdout."""
        carriers = self._controller.computer.carriers
        num = len(carriers)
        topology = self._controller.connection_manager.topology_mode or "direct"
        print(f"LUCIDAC stack -- {num} device(s), mode={topology}")
        for i, carrier in enumerate(carriers):
            mac = carrier.path.to_mac()
            prefix = "(*)" if i == 0 else "   "
            suffix = " (sync master)" if i == 0 else ""
            print(f"  {prefix} {mac}{suffix}")

# Copyright (c) 2022-2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
Integration tests for LUCIStack proxy mode (``with_proxy=True``).

These tests verify the proxy-mode-specific code path in LUCIStack:
- ``_init_proxy_mode`` validation (endpoint count, async context)
- ``_discover_proxy_devices`` async discovery of MACs through a Proxy
- Full ``LUCIStack(..., with_proxy=True)`` initialization from sync context
- View / indexing behavior after proxy-mode init

Infrastructure is set up via in-process DummyDAC + Proxy.  For tests
that exercise the sync ``__init__`` path (which internally calls
``asyncio.run``), the Proxy infrastructure runs in a background thread
with its own event loop.
"""

import asyncio
import logging
import threading
from contextlib import contextmanager
from ipaddress import IPv4Address
from typing import Generator

import pytest

from pybrid.mock import DummyDAC, DummyDACConfig, DummyDACMacMode
from pybrid.lucidac.controller import Controller as LUCIDACController
from pybrid.lucipy.computer import LucipyWrapper as LUCIStack
from pybrid.redac.controller import Controller as REDACController
from pybrid.redac.proxy import Proxy
from tests.conftest import get_test_port, get_test_proxy_port

logger = logging.getLogger(__name__)

# Port base for proxy tests — avoids collision with single (0..9)
# and multi (100..109) device tests.
_PORT_BASE = 200


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@contextmanager
def _proxy_infrastructure(
    num_backends: int = 1,
    lucidac_mode: bool = True,
    proxy_port_offset: int = 0,
) -> Generator[dict, None, None]:
    """
    Start DummyDAC(s) + REDAC Controller + Proxy in a background thread.

    Yields a dict with:
        proxy_port   -- TCP port of the running Proxy
        mac_mapping  -- {virtual_mac: real_path} used by the Proxy
        num_carriers -- total number of carriers behind the Proxy

    The infrastructure runs in a daemon thread with its own event loop
    so that the caller can invoke ``LUCIStack(..., with_proxy=True)``
    from a sync (no running loop) context.

    Args:
        num_backends:     Number of DummyDAC instances to start.
        lucidac_mode:     Whether DummyDACs emulate LUCIDAC (1 carrier each).
        proxy_port_offset: Offset added to ``get_test_proxy_port()`` so
                          concurrent tests don't collide.
    """
    ready = threading.Event()
    shutdown = threading.Event()
    result: dict = {}
    error: list = []

    proxy_port = get_test_proxy_port() + proxy_port_offset

    async def _run() -> None:
        dacs: list[DummyDAC] = []
        try:
            # Start DummyDAC backends.  Alternate MAC modes so each
            # instance gets a unique MAC (VIRTUAL="00-00-00-00-00-00",
            # PHYSICAL="AB-CD-EF-12-34-56").
            mac_modes = [DummyDACMacMode.VIRTUAL, DummyDACMacMode.PHYSICAL]
            for i in range(num_backends):
                config = DummyDACConfig(
                    lucidac_mode=lucidac_mode,
                    mac_mode=mac_modes[i % len(mac_modes)],
                )
                dac = DummyDAC("127.0.0.1", get_test_port(_PORT_BASE + i), config)
                await dac.__aenter__()
                dacs.append(dac)

            # Build REDAC controller connecting to all backends
            ctrl = REDACController(standalone=True)
            for dac in dacs:
                port = dac._server.sockets[0].getsockname()[1]
                await ctrl.add_device("127.0.0.1", port)

            # Derive MAC mapping from controller's device list
            carrier_paths = list(ctrl.devices.keys())
            mac_mapping = {}
            for i, path in enumerate(carrier_paths):
                virtual_mac = f"AA-AA-AA-AA-AA-{i:02X}"
                mac_mapping[virtual_mac] = str(path)
            partition_config = {"device": [list(mac_mapping.keys())]}

            async with Proxy(
                ctrl,
                host="127.0.0.1",
                port=proxy_port,
                mac_mapping=mac_mapping,
                partition_config=partition_config,
            ) as (proxy_obj, server):
                actual_port = server.sockets[0].getsockname()[1]
                result["proxy_port"] = actual_port
                result["mac_mapping"] = mac_mapping
                result["num_carriers"] = len(carrier_paths)
                ready.set()

                # Keep running until the test signals shutdown
                while not shutdown.is_set():
                    await asyncio.sleep(0.05)

        except Exception as exc:
            error.append(exc)
            ready.set()  # unblock the caller even on failure
        finally:
            for dac in reversed(dacs):
                try:
                    await dac.__aexit__(None, None, None)
                except Exception:
                    pass

    thread = threading.Thread(target=lambda: asyncio.run(_run()), daemon=True)
    thread.start()

    try:
        assert ready.wait(timeout=15), "Proxy infrastructure failed to start"
        if error:
            raise RuntimeError(
                f"Proxy infrastructure thread raised: {error[0]}"
            ) from error[0]
        yield result
    finally:
        shutdown.set()
        thread.join(timeout=5)


# =========================================================================
# 1. Validation — no infrastructure required
# =========================================================================

class TestLUCIStackProxyValidation:
    """Sync validation checks on ``_init_proxy_mode``."""

    def test_proxy_mode_rejects_multiple_endpoints(self):
        """
        ``LUCIStack("ep1", "ep2", with_proxy=True)`` must raise ValueError
        because proxy mode accepts exactly one endpoint.
        """
        with pytest.raises(ValueError, match="exactly one endpoint"):
            LUCIStack(
                "tcp://192.168.1.1:5732",
                "tcp://192.168.1.2:5732",
                with_proxy=True,
            )

    @pytest.mark.asyncio
    async def test_proxy_mode_rejects_async_context(self):
        """
        Creating ``LUCIStack(..., with_proxy=True)`` from an async context
        must raise ValueError mentioning 'async context'.
        """
        with pytest.raises(ValueError, match="async context"):
            LUCIStack(
                "tcp://127.0.0.1:5732",
                with_proxy=True,
            )


# =========================================================================
# 2. Async unit: _discover_proxy_devices
# =========================================================================

class TestDiscoverProxyDevices:
    """Async tests calling ``_discover_proxy_devices`` directly."""

    @pytest.mark.asyncio
    async def test_discover_single_device_behind_proxy(self):
        """
        One LUCIDAC DummyDAC behind a Proxy.

        ``_discover_proxy_devices`` should return a list with exactly
        one MAC entry.

        Verifies:
        - Discovery connects to the proxy and obtains entity information
        - Returned list has length 1
        """
        config = DummyDACConfig(
            lucidac_mode=True,
            mac_mode=DummyDACMacMode.VIRTUAL,
        )
        proxy_port = get_test_proxy_port() + 10

        async with DummyDAC("127.0.0.1", get_test_port(_PORT_BASE + 10), config) as dac:
            dac_port = dac._server.sockets[0].getsockname()[1]

            async with REDACController(standalone=True) as ctrl:
                await ctrl.add_device("127.0.0.1", dac_port)

                carrier_paths = list(ctrl.devices.keys())
                mac_mapping = {
                    f"BB-BB-BB-BB-BB-{i:02X}": str(p)
                    for i, p in enumerate(carrier_paths)
                }
                partition_config = {"device": [list(mac_mapping.keys())]}

                async with Proxy(
                    ctrl,
                    host="127.0.0.1",
                    port=proxy_port,
                    mac_mapping=mac_mapping,
                    partition_config=partition_config,
                ) as (proxy_obj, server):
                    actual_port = server.sockets[0].getsockname()[1]

                    # Call _discover_proxy_devices directly (bypass __init__)
                    stack = object.__new__(LUCIStack)
                    macs = await stack._discover_proxy_devices(
                        "127.0.0.1", actual_port
                    )

                    assert isinstance(macs, list), (
                        "_discover_proxy_devices should return a list"
                    )
                    assert len(macs) == 1, (
                        f"Expected 1 MAC behind single-device proxy, got {len(macs)}"
                    )
                    assert all(isinstance(m, str) for m in macs), (
                        "Each entry should be a string"
                    )

    @pytest.mark.asyncio
    async def test_discover_multiple_devices_behind_proxy(self):
        """
        Two LUCIDAC DummyDACs behind a single Proxy.

        ``_discover_proxy_devices`` should return a list with 2 MAC entries,
        one for each backend device.

        Verifies:
        - Discovery enumerates all devices behind the proxy
        - Returned MACs are distinct
        """
        # Use different MAC modes so each DummyDAC gets a unique MAC.
        # VIRTUAL returns "00-00-00-00-00-00", PHYSICAL returns
        # "AB-CD-EF-12-34-56".
        config1 = DummyDACConfig(
            lucidac_mode=True, mac_mode=DummyDACMacMode.VIRTUAL,
        )
        config2 = DummyDACConfig(
            lucidac_mode=True, mac_mode=DummyDACMacMode.PHYSICAL,
        )
        proxy_port = get_test_proxy_port() + 11

        async with DummyDAC("127.0.0.1", get_test_port(_PORT_BASE + 11), config1) as dac1:
            dac1_port = dac1._server.sockets[0].getsockname()[1]

            async with DummyDAC("127.0.0.1", get_test_port(_PORT_BASE + 12), config2) as dac2:
                dac2_port = dac2._server.sockets[0].getsockname()[1]

                async with REDACController(standalone=True) as ctrl:
                    await ctrl.add_device("127.0.0.1", dac1_port)
                    await ctrl.add_device("127.0.0.1", dac2_port)

                    carrier_paths = list(ctrl.devices.keys())
                    mac_mapping = {
                        f"CC-CC-CC-CC-CC-{i:02X}": str(p)
                        for i, p in enumerate(carrier_paths)
                    }
                    partition_config = {"device": [list(mac_mapping.keys())]}

                    async with Proxy(
                        ctrl,
                        host="127.0.0.1",
                        port=proxy_port,
                        mac_mapping=mac_mapping,
                        partition_config=partition_config,
                    ) as (proxy_obj, server):
                        actual_port = server.sockets[0].getsockname()[1]

                        stack = object.__new__(LUCIStack)
                        macs = await stack._discover_proxy_devices(
                            "127.0.0.1", actual_port
                        )

                        assert isinstance(macs, list)
                        assert len(macs) == 2, (
                            f"Expected 2 MACs behind two-device proxy, got {len(macs)}"
                        )
                        assert len(set(macs)) == 2, (
                            "MACs from distinct devices should be unique"
                        )


# =========================================================================
# 3. Full integration: LUCIStack(with_proxy=True) from sync context
# =========================================================================

class TestLUCIStackProxyIntegration:
    """
    Integration tests creating ``LUCIStack(..., with_proxy=True)`` from a
    sync context, with Proxy infrastructure running in a background thread.
    """

    def test_single_device_proxy_init(self):
        """
        Single LUCIDAC DummyDAC behind a Proxy.

        ``LUCIStack(proxy_endpoint, with_proxy=True)`` should:
        - initialise with ``_num_devices == 1``
        - register 1 endpoint
        - endpoint should point to the proxy host:port
        """
        with _proxy_infrastructure(
            num_backends=1, proxy_port_offset=20
        ) as infra:
            luci = LUCIStack(
                f"tcp://127.0.0.1:{infra['proxy_port']}",
                with_proxy=True,
            )

            assert luci._num_devices == 1, (
                "Should discover exactly 1 device behind proxy"
            )
            assert len(luci._endpoints) == 1, (
                "Should have 1 registered endpoint"
            )

            host, port = luci._endpoints[0]
            assert host == "127.0.0.1", (
                "Endpoint host should be the proxy address"
            )
            assert port == infra["proxy_port"], (
                "Endpoint port should be the proxy port"
            )

    def test_multiple_devices_proxy_init(self):
        """
        Two LUCIDAC DummyDACs behind a single Proxy.

        ``LUCIStack(proxy_endpoint, with_proxy=True)`` should:
        - initialise with ``_num_devices == 2``
        - register 2 endpoints, both pointing to the proxy
        """
        with _proxy_infrastructure(
            num_backends=2, proxy_port_offset=21
        ) as infra:
            luci = LUCIStack(
                f"tcp://127.0.0.1:{infra['proxy_port']}",
                with_proxy=True,
            )

            assert luci._num_devices == 2, (
                f"Should discover 2 devices, got {luci._num_devices}"
            )
            assert len(luci._endpoints) == 2

            for idx in range(2):
                host, port = luci._endpoints[idx]
                assert host == "127.0.0.1"
                assert port == infra["proxy_port"], (
                    "Both endpoints should point to the same proxy port"
                )

    def test_views_work_after_proxy_init(self):
        """
        After proxy-mode init with 2 devices, ``luci[0]`` and ``luci[1]``
        should return valid view objects (same behaviour as direct mode).

        Verifies:
        - ``__getitem__`` returns a LUCIStack marked as view
        - View device indices are correct
        - View shares the same circuits dict
        """
        with _proxy_infrastructure(
            num_backends=2, proxy_port_offset=22
        ) as infra:
            luci = LUCIStack(
                f"tcp://127.0.0.1:{infra['proxy_port']}",
                with_proxy=True,
            )

            view0 = luci[0]
            view1 = luci[1]

            assert isinstance(view0, LUCIStack)
            assert isinstance(view1, LUCIStack)

            assert view0._is_view is True
            assert view1._is_view is True

            assert view0._device_indices == [0]
            assert view1._device_indices == [1]

            assert view0._circuits is luci._circuits, (
                "View must share the root stack's circuits dict"
            )
            assert view1._circuits is luci._circuits

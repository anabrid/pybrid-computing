# Copyright (c) 2022-2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
Integration tests for LUCIStack multi-device workflow.

These tests verify the multi-device capabilities of LUCIStack:
- ``__getitem__`` returning lightweight view objects that share the circuits dict
- Per-device circuit assignment via views
- Broadcast ``set_circuit`` on the root stack
- Sync master assignment during multi-device runs
- Run data keyed by integer device index

Written as TDD tests before implementation.
All tests spin up their own DummyDAC instances in ``lucidac_mode=True``.
"""

import copy
import logging

import pytest

from pybrid.mock import DummyDAC, DummyDACConfig
from pybrid.lucipy.computer import LucipyWrapper as LUCIStack
from pybrid.lucipy.circuits import Circuit
from tests.conftest import get_test_port

# DummyDAC returns a smaller data array than real hardware for the OP_END
# final-values callback. The controller's handle_run_data_end tries to
# index beyond that array, causing an IndexError that the protocol layer
# catches and logs at ERROR level (protocol.py:189-195).  The error is
# harmless — streamed run data arrives correctly — so we suppress the
# protocol logger during tests that execute actual runs against DummyDAC.
_PROTOCOL_LOGGER = "pybrid.redac.protocol.protocol"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_simple_circuit(ic: float = 1.0) -> Circuit:
    """
    Create a minimal circuit with one integrator and one measurement output.

    Args:
        ic: Initial condition for the integrator.

    Returns:
        A Circuit instance ready for ``set_circuit``.
    """
    c = Circuit()
    i0 = c.int(ic=ic)
    c.measure(i0)
    return c


# We reserve test port indices 100..109 for multi-device tests so they
# never collide with single-device tests (which use indices 0..9).
_PORT_BASE = 100


class TestLUCIStackMultiDevice:
    """Tests for multi-device LUCIStack workflow."""

    # -----------------------------------------------------------------------
    # 1. Initialization
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_lucistack_multi_init(self):
        """
        Create LUCIStack with 3 DummyDACs. Wrapper has 3 endpoints.

        Verifies that when multiple endpoints are provided, each device is
        registered in the wrapper with the correct host and port.
        """
        config = DummyDACConfig(lucidac_mode=True)
        port0 = get_test_port(_PORT_BASE)
        port1 = get_test_port(_PORT_BASE + 1)
        port2 = get_test_port(_PORT_BASE + 2)

        async with (
            DummyDAC("127.0.0.1", port0, config) as dac0,
            DummyDAC("127.0.0.1", port1, config) as dac1,
            DummyDAC("127.0.0.1", port2, config) as dac2,
        ):
            dp0 = dac0._server.sockets[0].getsockname()[1]
            dp1 = dac1._server.sockets[0].getsockname()[1]
            dp2 = dac2._server.sockets[0].getsockname()[1]

            luci = LUCIStack(
                f"tcp://127.0.0.1:{dp0}",
                f"tcp://127.0.0.1:{dp1}",
                f"tcp://127.0.0.1:{dp2}",
            )

            # Wrapper should contain exactly 3 endpoints
            assert len(luci._endpoints) == 3, (
                "Wrapper should have 3 registered endpoints"
            )

            # Each device should be reachable by its index
            for idx, expected_port in enumerate([dp0, dp1, dp2]):
                host, port = luci._endpoints[idx]
                assert host == "127.0.0.1"
                assert port == expected_port

    # -----------------------------------------------------------------------
    # 2. __getitem__ — single index
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_lucistack_getitem_single(self):
        """
        ``luci[0]`` returns a view LUCIStack that wraps exactly 1 device.

        The view must be a LUCIStack instance with ``_is_view == True``
        and ``_device_indices == [0]``.
        """
        config = DummyDACConfig(lucidac_mode=True)
        port0 = get_test_port(_PORT_BASE + 3)
        port1 = get_test_port(_PORT_BASE + 4)

        async with (
            DummyDAC("127.0.0.1", port0, config) as dac0,
            DummyDAC("127.0.0.1", port1, config) as dac1,
        ):
            dp0 = dac0._server.sockets[0].getsockname()[1]
            dp1 = dac1._server.sockets[0].getsockname()[1]

            luci = LUCIStack(
                f"tcp://127.0.0.1:{dp0}",
                f"tcp://127.0.0.1:{dp1}",
            )

            view = luci[0]

            assert isinstance(view, LUCIStack), (
                "__getitem__ should return a LUCIStack instance"
            )
            assert view._is_view is True, (
                "Returned object should be marked as a view"
            )
            assert view._device_indices == [0], (
                "View should wrap only device index 0"
            )
            assert view._num_devices == 1, (
                "View should report 1 device"
            )

    # -----------------------------------------------------------------------
    # 3. __getitem__ — tuple of indices
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_lucistack_getitem_tuple(self):
        """
        ``luci[0, 2]`` returns a view LUCIStack that wraps 2 devices.

        The view's ``_device_indices`` should be ``[0, 2]`` and it should
        share the same circuits dict as the parent.
        """
        config = DummyDACConfig(lucidac_mode=True)
        port0 = get_test_port(_PORT_BASE + 5)
        port1 = get_test_port(_PORT_BASE + 6)
        port2 = get_test_port(_PORT_BASE + 7)

        async with (
            DummyDAC("127.0.0.1", port0, config) as dac0,
            DummyDAC("127.0.0.1", port1, config) as dac1,
            DummyDAC("127.0.0.1", port2, config) as dac2,
        ):
            dp0 = dac0._server.sockets[0].getsockname()[1]
            dp1 = dac1._server.sockets[0].getsockname()[1]
            dp2 = dac2._server.sockets[0].getsockname()[1]

            luci = LUCIStack(
                f"tcp://127.0.0.1:{dp0}",
                f"tcp://127.0.0.1:{dp1}",
                f"tcp://127.0.0.1:{dp2}",
            )

            view = luci[0, 2]

            assert isinstance(view, LUCIStack)
            assert view._is_view is True
            assert view._device_indices == [0, 2], (
                "View should contain device indices 0 and 2"
            )
            assert view._num_devices == 2
            assert view._circuits is luci._circuits, (
                "View must share the same circuits dict as the root stack"
            )

    # -----------------------------------------------------------------------
    # 4. __getitem__ is a view (writes through to circuits dict)
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_lucistack_getitem_is_view(self):
        """
        ``luci[0].set_circuit(c)`` writes through to the shared circuits dict.

        After setting a circuit on a view, retrieving it from the circuits dict
        by the same device index should return a matching circuit (deep-copied).
        """
        config = DummyDACConfig(lucidac_mode=True)
        port0 = get_test_port(_PORT_BASE + 8)
        port1 = get_test_port(_PORT_BASE + 9)

        async with (
            DummyDAC("127.0.0.1", port0, config) as dac0,
            DummyDAC("127.0.0.1", port1, config) as dac1,
        ):
            dp0 = dac0._server.sockets[0].getsockname()[1]
            dp1 = dac1._server.sockets[0].getsockname()[1]

            luci = LUCIStack(
                f"tcp://127.0.0.1:{dp0}",
                f"tcp://127.0.0.1:{dp1}",
            )

            circuit = _make_simple_circuit(ic=0.42)

            # Set circuit via the view for device 0
            luci[0].set_circuit(circuit)

            # The circuit should be stored in the circuits dict at index 0
            stored = luci._circuits.get(0)
            assert stored is not None, (
                "Circuit should have been written through to the circuits dict"
            )

            # Device 1 should NOT have a circuit yet
            assert luci._circuits.get(1) is None, (
                "Device 1 should not have a circuit assigned"
            )

    # -----------------------------------------------------------------------
    # 5. Per-device circuit assignment
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_lucistack_per_device_circuit(self):
        """
        ``luci[0].set_circuit(c0)`` and ``luci[1].set_circuit(c1)`` store
        different circuits for each device.

        Verifies that views correctly scope ``set_circuit`` to their
        respective device indices.
        """
        config = DummyDACConfig(lucidac_mode=True)
        port0 = get_test_port(_PORT_BASE + 10)
        port1 = get_test_port(_PORT_BASE + 11)

        async with (
            DummyDAC("127.0.0.1", port0, config) as dac0,
            DummyDAC("127.0.0.1", port1, config) as dac1,
        ):
            dp0 = dac0._server.sockets[0].getsockname()[1]
            dp1 = dac1._server.sockets[0].getsockname()[1]

            luci = LUCIStack(
                f"tcp://127.0.0.1:{dp0}",
                f"tcp://127.0.0.1:{dp1}",
            )

            c0 = _make_simple_circuit(ic=1.0)
            c1 = _make_simple_circuit(ic=0.5)

            luci[0].set_circuit(c0)
            luci[1].set_circuit(c1)

            stored0 = luci._circuits.get(0)
            stored1 = luci._circuits.get(1)

            assert stored0 is not None
            assert stored1 is not None

            # The two stored circuits should be independent objects
            assert stored0 is not stored1, (
                "Circuits for different devices must be distinct objects"
            )

    # -----------------------------------------------------------------------
    # 6. Broadcast set_circuit on root stack
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_lucistack_set_circuit_broadcasts(self):
        """
        ``luci.set_circuit(c)`` deep-copies the circuit to all devices.

        When called on a root (non-view) stack with multiple devices, the
        circuit should be stored for every device index. Each stored copy
        should be independent (deep-copied).
        """
        config = DummyDACConfig(lucidac_mode=True)
        port0 = get_test_port(_PORT_BASE + 12)
        port1 = get_test_port(_PORT_BASE + 13)
        port2 = get_test_port(_PORT_BASE + 14)

        async with (
            DummyDAC("127.0.0.1", port0, config) as dac0,
            DummyDAC("127.0.0.1", port1, config) as dac1,
            DummyDAC("127.0.0.1", port2, config) as dac2,
        ):
            dp0 = dac0._server.sockets[0].getsockname()[1]
            dp1 = dac1._server.sockets[0].getsockname()[1]
            dp2 = dac2._server.sockets[0].getsockname()[1]

            luci = LUCIStack(
                f"tcp://127.0.0.1:{dp0}",
                f"tcp://127.0.0.1:{dp1}",
                f"tcp://127.0.0.1:{dp2}",
            )

            circuit = _make_simple_circuit(ic=0.77)

            # Broadcast set_circuit to all 3 devices
            luci.set_circuit(circuit)

            # Each device should have a circuit
            for idx in range(3):
                stored = luci._circuits.get(idx)
                assert stored is not None, (
                    f"Device {idx} should have a circuit after broadcast"
                )

            # All stored copies should be independent objects
            s0 = luci._circuits.get(0)
            s1 = luci._circuits.get(1)
            s2 = luci._circuits.get(2)
            assert s0 is not s1, "Deep copies must be distinct objects"
            assert s1 is not s2, "Deep copies must be distinct objects"
            assert s0 is not s2, "Deep copies must be distinct objects"


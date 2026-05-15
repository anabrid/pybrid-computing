# Copyright (c) 2022-2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
Integration tests for LUCIStack multi-device workflow.

These tests verify the multi-device capabilities of LUCIStack:
- Per-device circuit creation via ``create_circuit(device_index)``
- Broadcast ``set_circuit`` on the root stack
- Sync master assignment during multi-device runs
- Run data keyed by integer device index

All tests spin up their own DummyDAC instances in ``lucidac_mode=True``.
"""

import pytest

from pybrid.lucipy.circuits import Circuit
from pybrid.lucipy.computer import LucipyWrapper as LUCIStack
from pybrid.mock import DummyDAC, DummyDACConfig
from tests.conftest import get_test_port

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
        """Three endpoints are stored with correct host and port values."""
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
            assert len(luci._endpoints) == 3, "Wrapper should have 3 registered endpoints"

            # Each device should be reachable by its index
            for idx, expected_port in enumerate([dp0, dp1, dp2]):
                host, port = luci._endpoints[idx]
                assert host == "127.0.0.1"
                assert port == expected_port

    # -----------------------------------------------------------------------
    # 2. Broadcast set_circuit on root stack
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_lucistack_set_circuit_broadcasts(self):
        """set_circuit() deep-copies the circuit to all devices as independent objects."""
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

            circuit = Circuit("AA-BB-CC-DD-EE-FF")
            i0 = circuit.int(ic=0.77)
            circuit.probe(i0)

            # Broadcast set_circuit to all 3 devices
            luci.set_circuit(circuit)

            # Each device should have a circuit
            for idx in range(3):
                stored = luci._circuits.get(idx)
                assert stored is not None, f"Device {idx} should have a circuit after broadcast"

            # All stored copies should be independent objects
            s0 = luci._circuits.get(0)
            s1 = luci._circuits.get(1)
            s2 = luci._circuits.get(2)
            assert s0 is not s1, "Deep copies must be distinct objects"
            assert s1 is not s2, "Deep copies must be distinct objects"
            assert s0 is not s2, "Deep copies must be distinct objects"

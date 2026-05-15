# Copyright (c) 2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
Integration tests for LucipyWrapper multi-device workflow.

These tests verify multi-device behavior with the single-controller
architecture:

- **create_circuit(device_index)** stores circuits by reference
- **set_circuit()** broadcasts a deep copy to all devices
- Topology detection (direct mode) works with two endpoints

Uses two DummyDAC instances with different MAC modes to simulate two
distinct LUCIDAC devices.
"""

import logging

import pytest

from pybrid.lucipy.circuits import Circuit
from pybrid.lucipy.computer import LucipyWrapper
from pybrid.mock import DummyDAC, DummyDACConfig, DummyDACMacMode
from tests.conftest import get_test_port

# Suppress harmless DummyDAC protocol errors during run tests.
_PROTOCOL_LOGGER = "pybrid.redac.protocol.protocol"

# Port base offset -- avoids collision with single-device tests (300)
# and old multi-device tests (100).
_PORT_BASE = 400


class TestLucipyWrapperMultiDevice:
    """Tests for multi-device LucipyWrapper workflow."""

    @pytest.mark.asyncio
    async def test_two_devices_direct(self):
        """Two endpoint LucipyWrapper discovers exactly 2 carriers after _ensure_controller()."""
        config_v = DummyDACConfig(
            lucidac_mode=True,
            mac_mode=DummyDACMacMode.VIRTUAL,
        )
        config_p = DummyDACConfig(
            lucidac_mode=True,
            mac_mode=DummyDACMacMode.PHYSICAL,
        )
        port0 = get_test_port(_PORT_BASE)
        port1 = get_test_port(_PORT_BASE + 1)

        async with (
            DummyDAC("127.0.0.1", port0, config_v) as dac0,
            DummyDAC("127.0.0.1", port1, config_p) as dac1,
        ):
            dp0 = dac0._server.sockets[0].getsockname()[1]
            dp1 = dac1._server.sockets[0].getsockname()[1]

            wrapper = LucipyWrapper(
                f"tcp://127.0.0.1:{dp0}",
                f"tcp://127.0.0.1:{dp1}",
            )

            await wrapper._ensure_controller()

            assert wrapper._controller is not None, "Controller should be initialized"
            assert (
                len(wrapper._controller.computer.carriers) == 2
            ), "Two-device wrapper should discover exactly 2 carriers"

            await wrapper.close()

    @pytest.mark.asyncio
    async def test_create_circuit_per_device(self):
        """create_circuit(0) and create_circuit(1) store distinct Circuit objects by reference."""
        config_v = DummyDACConfig(
            lucidac_mode=True,
            mac_mode=DummyDACMacMode.VIRTUAL,
        )
        config_p = DummyDACConfig(
            lucidac_mode=True,
            mac_mode=DummyDACMacMode.PHYSICAL,
        )
        port0 = get_test_port(_PORT_BASE + 2)
        port1 = get_test_port(_PORT_BASE + 3)

        async with (
            DummyDAC("127.0.0.1", port0, config_v) as dac0,
            DummyDAC("127.0.0.1", port1, config_p) as dac1,
        ):
            dp0 = dac0._server.sockets[0].getsockname()[1]
            dp1 = dac1._server.sockets[0].getsockname()[1]

            wrapper = LucipyWrapper(
                f"tcp://127.0.0.1:{dp0}",
                f"tcp://127.0.0.1:{dp1}",
            )

            await wrapper._ensure_controller()

            c0 = wrapper.create_circuit(0)
            c1 = wrapper.create_circuit(1)

            assert 0 in wrapper._circuits, "Circuit for device 0 should be stored in _circuits"
            assert 1 in wrapper._circuits, "Circuit for device 1 should be stored in _circuits"
            assert wrapper._circuits[0] is c0, "Circuit 0 should be stored by reference"
            assert wrapper._circuits[1] is c1, "Circuit 1 should be stored by reference"
            assert c0 is not c1, "Circuits for different devices must be distinct objects"

            await wrapper.close()

    @pytest.mark.asyncio
    async def test_create_circuit_mutations_visible(self):
        """Mutations to the circuit returned by create_circuit are visible through _circuits (same object)."""
        config_v = DummyDACConfig(
            lucidac_mode=True,
            mac_mode=DummyDACMacMode.VIRTUAL,
        )
        config_p = DummyDACConfig(
            lucidac_mode=True,
            mac_mode=DummyDACMacMode.PHYSICAL,
        )
        port0 = get_test_port(_PORT_BASE + 4)
        port1 = get_test_port(_PORT_BASE + 5)

        async with (
            DummyDAC("127.0.0.1", port0, config_v) as dac0,
            DummyDAC("127.0.0.1", port1, config_p) as dac1,
        ):
            dp0 = dac0._server.sockets[0].getsockname()[1]
            dp1 = dac1._server.sockets[0].getsockname()[1]

            wrapper = LucipyWrapper(
                f"tcp://127.0.0.1:{dp0}",
                f"tcp://127.0.0.1:{dp1}",
            )

            await wrapper._ensure_controller()

            c0 = wrapper.create_circuit(0)

            # Mutate the circuit after creation
            i0 = c0.int(ic=0.42)
            c0.probe(i0)

            # The stored circuit sees the mutation (same object)
            stored = wrapper._circuits[0]
            assert stored._integrators_used[0] is True, "Mutation on returned circuit must be visible in _circuits"

            await wrapper.close()

    @pytest.mark.asyncio
    async def test_topology_detection_multi_direct(self):
        """Two direct endpoints result in topology_mode='direct' (each connection owns 1 carrier)."""
        config_v = DummyDACConfig(
            lucidac_mode=True,
            mac_mode=DummyDACMacMode.VIRTUAL,
        )
        config_p = DummyDACConfig(
            lucidac_mode=True,
            mac_mode=DummyDACMacMode.PHYSICAL,
        )
        port0 = get_test_port(_PORT_BASE + 6)
        port1 = get_test_port(_PORT_BASE + 7)

        async with (
            DummyDAC("127.0.0.1", port0, config_v) as dac0,
            DummyDAC("127.0.0.1", port1, config_p) as dac1,
        ):
            dp0 = dac0._server.sockets[0].getsockname()[1]
            dp1 = dac1._server.sockets[0].getsockname()[1]

            wrapper = LucipyWrapper(
                f"tcp://127.0.0.1:{dp0}",
                f"tcp://127.0.0.1:{dp1}",
            )

            await wrapper._ensure_controller()

            assert wrapper._controller.connection_manager.topology_mode == "direct", (
                "Two direct endpoints should result in topology_mode='direct' "
                "(2 connections, 1 path each -- no proxy detected)"
            )

            await wrapper.close()


class TestLucipyWrapperMultiDeviceDefaults:
    """Tests for automatic default-circuit population in multi-device setups."""

    @pytest.mark.asyncio
    async def test_run_succeeds_with_single_explicit_circuit(self):
        """Only device 0 gets an explicit circuit; device 1 auto-receives an
        empty default circuit so _run() does not raise."""
        config_v = DummyDACConfig(
            lucidac_mode=True,
            mac_mode=DummyDACMacMode.VIRTUAL,
        )
        config_p = DummyDACConfig(
            lucidac_mode=True,
            mac_mode=DummyDACMacMode.PHYSICAL,
        )
        port0 = get_test_port(_PORT_BASE + 8)
        port1 = get_test_port(_PORT_BASE + 9)

        async with (
            DummyDAC("127.0.0.1", port0, config_v) as dac0,
            DummyDAC("127.0.0.1", port1, config_p) as dac1,
        ):
            dp0 = dac0._server.sockets[0].getsockname()[1]
            dp1 = dac1._server.sockets[0].getsockname()[1]

            wrapper = LucipyWrapper(
                f"tcp://127.0.0.1:{dp0}",
                f"tcp://127.0.0.1:{dp1}",
            )

            await wrapper._ensure_controller()

            # Only set a circuit for device 0
            c0 = wrapper.create_circuit(0)
            i0 = c0.int(ic=0.5)
            c0.probe(i0, adc_channel=0)

            # Device 1 should have auto-received a default circuit
            assert 1 in wrapper._circuits, "Device 1 should have an auto-populated default circuit"

            # Verify default circuit has the correct MAC
            expected_mac = wrapper._controller.computer.carriers[1].path.to_mac()
            default_circuit = wrapper._circuits[1]
            default_mac = default_circuit._lucidac.entities[0].path.to_mac()
            assert default_mac == expected_mac, (
                f"Default circuit MAC {default_mac} should match " f"carrier 1 MAC {expected_mac}"
            )

            await wrapper.close()

    @pytest.mark.asyncio
    async def test_create_circuit_defaults_to_device_zero(self):
        """create_circuit() without index defaults to device 0 in multi-device setups."""
        config_v = DummyDACConfig(
            lucidac_mode=True,
            mac_mode=DummyDACMacMode.VIRTUAL,
        )
        config_p = DummyDACConfig(
            lucidac_mode=True,
            mac_mode=DummyDACMacMode.PHYSICAL,
        )
        port0 = get_test_port(_PORT_BASE + 10)
        port1 = get_test_port(_PORT_BASE + 11)

        async with (
            DummyDAC("127.0.0.1", port0, config_v) as dac0,
            DummyDAC("127.0.0.1", port1, config_p) as dac1,
        ):
            dp0 = dac0._server.sockets[0].getsockname()[1]
            dp1 = dac1._server.sockets[0].getsockname()[1]

            wrapper = LucipyWrapper(
                f"tcp://127.0.0.1:{dp0}",
                f"tcp://127.0.0.1:{dp1}",
            )

            await wrapper._ensure_controller()

            # No explicit device_index — should default to 0
            c = wrapper.create_circuit()

            expected_mac = wrapper._controller.computer.carriers[0].path.to_mac()
            circuit_mac = c._lucidac.entities[0].path.to_mac()
            assert circuit_mac == expected_mac, (
                f"Default create_circuit() should target device 0 " f"(MAC {expected_mac}), got {circuit_mac}"
            )
            assert wrapper._circuits[0] is c

            await wrapper.close()

    @pytest.mark.asyncio
    async def test_explicit_circuit_not_overwritten_by_defaults(self):
        """An explicitly created circuit is preserved — _ensure_controller()
        does not replace it with a default."""
        config_v = DummyDACConfig(
            lucidac_mode=True,
            mac_mode=DummyDACMacMode.VIRTUAL,
        )
        config_p = DummyDACConfig(
            lucidac_mode=True,
            mac_mode=DummyDACMacMode.PHYSICAL,
        )
        port0 = get_test_port(_PORT_BASE + 12)
        port1 = get_test_port(_PORT_BASE + 13)

        async with (
            DummyDAC("127.0.0.1", port0, config_v) as dac0,
            DummyDAC("127.0.0.1", port1, config_p) as dac1,
        ):
            dp0 = dac0._server.sockets[0].getsockname()[1]
            dp1 = dac1._server.sockets[0].getsockname()[1]

            wrapper = LucipyWrapper(
                f"tcp://127.0.0.1:{dp0}",
                f"tcp://127.0.0.1:{dp1}",
            )

            await wrapper._ensure_controller()

            # Create and mutate a circuit for device 0
            c0 = wrapper.create_circuit(0)
            c0.int(ic=0.42)

            # Trigger default-population path again (idempotent)
            await wrapper._ensure_controller()

            # The user's circuit must not have been replaced
            assert wrapper._circuits[0] is c0, "Explicit circuit for device 0 must not be overwritten by defaults"
            assert c0._integrators_used[0] is True, "User's circuit mutations must be preserved"

            await wrapper.close()

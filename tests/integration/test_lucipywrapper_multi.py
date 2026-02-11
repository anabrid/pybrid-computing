# Copyright (c) 2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
Integration tests for LucipyWrapper multi-device workflow (Sprint 2).

These tests verify multi-device behavior with the NEW single-controller
architecture.  Key difference from the old LUCIStack:

- **Old**: N controllers, one per device, independent connections
- **New**: ONE controller with all devices added, shared state via ``_circuits`` dict

Uses two DummyDAC instances with different MAC modes to simulate two
distinct LUCIDAC devices.

Written as TDD tests -- they will FAIL until Sprint 2 implementation lands.
"""

import logging

import pytest

from pybrid.mock import DummyDAC, DummyDACConfig, DummyDACMacMode
from tests.conftest import get_test_port

from pybrid.lucipy.computer import LucipyWrapper
from pybrid.lucipy.circuits import Circuit

# Suppress harmless DummyDAC protocol errors during run tests.
_PROTOCOL_LOGGER = "pybrid.redac.protocol.protocol"

# Port base offset -- avoids collision with single-device tests (300)
# and old multi-device tests (100).
_PORT_BASE = 400


def _make_simple_circuit(ic: float = 1.0) -> Circuit:
    """
    Create a minimal circuit with one integrator and one measurement output.

    Args:
        ic: Initial condition for the integrator.

    Returns:
        A Circuit instance ready for ``set_circuit()``.
    """
    c = Circuit()
    i0 = c.int(ic=ic)
    c.measure(i0)
    return c


def _guard_new_api(wrapper):
    """
    Fail the test cleanly if the wrapper is still the old LUCIStack.

    Checks for the ``_ensure_controller`` method which only exists on
    the new LucipyWrapper class.
    """
    if not hasattr(wrapper, "_ensure_controller"):
        pytest.fail(
            "LucipyWrapper._ensure_controller() not yet implemented "
            "(still using old LUCIStack API)"
        )


class TestLucipyWrapperMultiDevice:
    """Tests for multi-device LucipyWrapper workflow."""

    @pytest.mark.asyncio
    async def test_two_devices_direct(self):
        """
        Two DummyDACs -> LucipyWrapper(ep1, ep2) -> single controller.

        After ``_ensure_controller()``, the controller's computer should
        have exactly 2 carriers registered.
        """
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
            _guard_new_api(wrapper)

            await wrapper._ensure_controller()

            assert wrapper._controller is not None, (
                "Controller should be initialized"
            )
            assert len(wrapper._controller.computer.carriers) == 2, (
                "Two-device wrapper should discover exactly 2 carriers"
            )

            await wrapper.close()

    @pytest.mark.asyncio
    async def test_per_device_circuit_via_view(self):
        """
        ``wrapper[0].set_circuit(c0)`` and ``wrapper[1].set_circuit(c1)``
        should store different circuits in the wrapper's ``_circuits`` dict.
        """
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
            _guard_new_api(wrapper)

            c0 = _make_simple_circuit(ic=1.0)
            c1 = _make_simple_circuit(ic=0.5)

            wrapper[0].set_circuit(c0)
            wrapper[1].set_circuit(c1)

            # The new wrapper stores circuits in a _circuits dict keyed by
            # device index (shared between root and views).
            if not hasattr(wrapper, "_circuits"):
                pytest.fail(
                    "LucipyWrapper._circuits dict not found "
                    "(still using old pool-based storage)"
                )

            assert 0 in wrapper._circuits, (
                "Circuit for device 0 should be stored in _circuits"
            )
            assert 1 in wrapper._circuits, (
                "Circuit for device 1 should be stored in _circuits"
            )
            assert wrapper._circuits[0] is not wrapper._circuits[1], (
                "Circuits for different devices must be distinct objects"
            )

    @pytest.mark.asyncio
    async def test_view_shares_circuits_with_parent(self):
        """
        A view created via ``wrapper[0]`` should share the same ``_circuits``
        dict object as the parent wrapper.  Writing a circuit on the view
        must be visible to the parent.
        """
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
            _guard_new_api(wrapper)

            # Get a view for device 0
            view = wrapper[0]

            # Check that the view shares the same _circuits dict reference
            if not hasattr(wrapper, "_circuits"):
                pytest.fail(
                    "LucipyWrapper._circuits dict not found "
                    "(still using old pool-based storage)"
                )

            assert view._circuits is wrapper._circuits, (
                "View's _circuits must be the SAME dict object as parent's "
                "(shared reference, not a copy)"
            )

            # Set circuit via view and verify parent sees it
            circuit = _make_simple_circuit(ic=0.42)
            view.set_circuit(circuit)

            assert 0 in wrapper._circuits, (
                "Circuit set on view[0] should appear in parent's _circuits"
            )

    @pytest.mark.asyncio
    async def test_standalone_detection_multi_direct(self):
        """
        Two direct endpoints -> after ``_ensure_controller()``, the wrapper's
        controller should have ``standalone == True``.

        Rationale: 2 protocols, each managing 1 carrier path -- no single
        protocol manages multiple paths, so this is direct (not proxy) mode.
        """
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
            _guard_new_api(wrapper)

            await wrapper._ensure_controller()

            assert wrapper._controller.standalone is True, (
                "Two direct endpoints should result in standalone=True "
                "(2 protocols, 1 path each -- no proxy detected)"
            )

            await wrapper.close()

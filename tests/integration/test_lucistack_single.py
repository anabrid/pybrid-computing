# Copyright (c) 2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
Integration tests for LUCIStack single-device workflow.

These tests verify the LucipyWrapper class (aliased as LUCIStack/LUCIDAC) with
single-device scenarios. Uses DummyDAC in LUCIDAC mode for testing.
"""

import asyncio
import logging
import os
from unittest.mock import AsyncMock, patch

import pytest

from pybrid.lucipy.circuits import Circuit
from pybrid.lucipy.computer import LucipyWrapper as LUCIStack
from pybrid.mock import DummyDAC, DummyDACConfig
from tests.conftest import get_test_port

# Tests that execute a full run cycle (set_circuit → run) require the native
# C++ ControlChannel binding for config send and run state callbacks.
try:
    from pybrid.native._impl import ControlChannel as _NativeCC

    _NATIVE_AVAILABLE = True
except ImportError:
    _NATIVE_AVAILABLE = False

_requires_native = pytest.mark.skipif(
    not _NATIVE_AVAILABLE,
    reason="Full run cycle requires native C++ ControlChannel (pybrid-computing-native not built)",
)

# DummyDAC returns a smaller data array than real hardware for the OP_END
# final-values callback. The controller's handle_run_data_end tries to
# index beyond that array, causing an IndexError that the protocol layer
# catches and logs at ERROR level (protocol.py:189-195).  The error is
# harmless — streamed run data arrives correctly — so we suppress the
# protocol logger during tests that execute actual runs against DummyDAC.
_PROTOCOL_LOGGER = "pybrid.redac.protocol.protocol"


class TestLUCIStackSingleDevice:
    """Tests for single-device LucipyWrapper workflow."""

    @pytest.mark.asyncio
    @_requires_native
    async def test_lucistack_set_circuit_and_run(self):
        """Full single-device workflow: set_circuit, set_daq, set_run, _run() returns a Run with data."""
        config = DummyDACConfig(lucidac_mode=True)
        port = get_test_port(1)

        async with DummyDAC("127.0.0.1", port, config) as dac:
            dac_port = dac._server.sockets[0].getsockname()[1]

            # Create LUCIStack
            luci = LUCIStack(f"tcp://127.0.0.1:{dac_port}")

            # Create a simple circuit
            circuit = Circuit("AA-BB-CC-DD-EE-FF")
            i0 = circuit.int(ic=1.0)
            circuit.probe(i0)  # Greedy assignment

            # Set circuit
            luci.set_circuit(circuit)

            # Set DAQ config
            luci.set_daq(sample_rate=1000)

            # Set run config
            luci.set_run(ic_time=100_000, op_time=10_000_000)  # nanoseconds  # nanoseconds

            # Suppress protocol logger — see _PROTOCOL_LOGGER comment above.
            logging.getLogger(_PROTOCOL_LOGGER).setLevel(logging.CRITICAL)
            try:
                run = await luci._run()
            finally:
                logging.getLogger(_PROTOCOL_LOGGER).setLevel(logging.NOTSET)

            # Verify Run object
            assert run is not None, "run() should return a Run object"

    @pytest.mark.asyncio
    @_requires_native
    async def test_lucistack_num_channels_deduced(self):
        """Circuit with 3 probe() calls causes LUCIStack to auto-deduce 3 DAQ channels."""
        config = DummyDACConfig(lucidac_mode=True)
        port = get_test_port(4)

        async with DummyDAC("127.0.0.1", port, config) as dac:
            dac_port = dac._server.sockets[0].getsockname()[1]

            # Create LUCIStack
            luci = LUCIStack(f"tcp://127.0.0.1:{dac_port}")

            # Create circuit with 3 outputs
            circuit = Circuit("AA-BB-CC-DD-EE-FF")
            i0 = circuit.int(ic=1.0)
            i1 = circuit.int(ic=0.5)
            i2 = circuit.int(ic=0.25)

            circuit.probe(i0)  # Channel 0
            circuit.probe(i1)  # Channel 1
            circuit.probe(i2)  # Channel 2

            # Set circuit (should auto-detect 3 channels)
            luci.set_circuit(circuit)

            # Set DAQ without explicit num_channels
            luci.set_daq(sample_rate=1000)

            # Set run config
            luci.set_run(ic_time=100_000, op_time=10_000_000)  # nanoseconds  # nanoseconds

            # Suppress protocol logger — see _PROTOCOL_LOGGER comment above.
            logging.getLogger(_PROTOCOL_LOGGER).setLevel(logging.CRITICAL)
            try:
                run = await luci._run()
            finally:
                logging.getLogger(_PROTOCOL_LOGGER).setLevel(logging.NOTSET)

            assert run is not None

    @pytest.mark.asyncio
    async def test_lucistack_no_endpoint_error(self):
        """LUCIDAC() with no args and no LUCIDAC_ENDPOINT raises ValueError('Auto-detection failed')."""
        # Ensure environment variable is not set
        original_env = os.environ.get("LUCIDAC_ENDPOINT")
        try:
            os.environ.pop("LUCIDAC_ENDPOINT", None)

            # Import LUCIDAC alias
            from pybrid.lucipy import LUCIDAC

            # Create with no args - should raise ValueError
            # (auto-detection cannot run from async context)
            with pytest.raises(ValueError, match="Auto-detection failed"):
                LUCIDAC()

        finally:
            # Restore original environment
            if original_env is not None:
                os.environ["LUCIDAC_ENDPOINT"] = original_env

    @pytest.mark.asyncio
    async def test_lucistack_bare_ip_port_endpoint(self):
        """Bare IP:PORT string without tcp:// scheme is accepted and parsed correctly."""
        config = DummyDACConfig(lucidac_mode=True)
        port = get_test_port(7)

        async with DummyDAC("127.0.0.1", port, config) as dac:
            dac_port = dac._server.sockets[0].getsockname()[1]

            luci = LUCIStack(f"127.0.0.1:{dac_port}")

            assert luci._endpoints[0][0] == "127.0.0.1"
            assert luci._endpoints[0][1] == dac_port

    @pytest.mark.asyncio
    async def test_lucistack_bare_ip_default_port(self):
        """Bare IP without port defaults to port 5732."""
        luci = LUCIStack("192.168.1.100")

        assert luci._endpoints[0][0] == "192.168.1.100"
        assert luci._endpoints[0][1] == 5732, "Should use default port when none specified"

    def test_lucistack_no_endpoint_error_sync(self):
        """LUCIDAC() with no args and a mocked empty network raises ValueError('No LUCIDAC found')."""
        # Ensure environment variable is not set
        original_env = os.environ.get("LUCIDAC_ENDPOINT")
        try:
            os.environ.pop("LUCIDAC_ENDPOINT", None)

            # Import LUCIDAC alias
            from pybrid.lucipy import LUCIDAC

            # Mock detect_in_network to raise TimeoutError (no devices)
            mock_detect = AsyncMock(side_effect=asyncio.TimeoutError("No available network devices found."))
            with patch("pybrid.lucipy.computer.detect_in_network", mock_detect):
                # Create with no args - should raise ValueError
                with pytest.raises(ValueError, match="No LUCIDAC found"):
                    LUCIDAC()

        finally:
            # Restore original environment
            if original_env is not None:
                os.environ["LUCIDAC_ENDPOINT"] = original_env

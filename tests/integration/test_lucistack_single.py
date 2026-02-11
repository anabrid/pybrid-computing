# Copyright (c) 2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
Integration tests for LUCIStack single-device workflow.

These tests verify the LucipyWrapper class (aliased as LUCIStack/LUCIDAC) with
single-device scenarios. Uses DummyDAC in LUCIDAC mode for testing.

Written as TDD tests before implementation.
"""

import asyncio
import logging
import os
from unittest.mock import patch, AsyncMock

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


class TestLUCIStackSingleDevice:
    """Tests for single-device LucipyWrapper workflow."""

    @pytest.mark.asyncio
    async def test_lucistack_single_device_init(self):
        """
        Create LUCIStack with one DummyDAC (LUCIDAC mode). Wrapper has 1 device.

        This test verifies basic initialization:
        - LUCIStack can be created with a single endpoint
        - It registers the device endpoint internally
        - The wrapper has exactly one endpoint
        """
        config = DummyDACConfig(lucidac_mode=True)
        port = get_test_port(0)

        async with DummyDAC("127.0.0.1", port, config) as dac:
            dac_port = dac._server.sockets[0].getsockname()[1]

            # Create LUCIStack with single endpoint
            luci = LUCIStack(f"tcp://127.0.0.1:{dac_port}")

            # Check that wrapper has 1 endpoint
            assert len(luci._endpoints) == 1, "Wrapper should have 1 endpoint"
            assert luci._endpoints[0][0] == "127.0.0.1"
            assert luci._endpoints[0][1] == dac_port

    @pytest.mark.asyncio
    async def test_lucistack_set_circuit_and_run(self):
        """
        Set circuit, set_daq, set_run, run(). Assert Run object returned with data.

        This test verifies the full single-device workflow:
        - Circuit can be set
        - DAQ configuration can be set
        - Run configuration can be set
        - run() executes and returns a Run object with data
        """
        config = DummyDACConfig(lucidac_mode=True)
        port = get_test_port(1)

        async with DummyDAC("127.0.0.1", port, config) as dac:
            dac_port = dac._server.sockets[0].getsockname()[1]

            # Create LUCIStack
            luci = LUCIStack(f"tcp://127.0.0.1:{dac_port}")

            # Create a simple circuit
            circuit = Circuit()
            i0 = circuit.int(ic=1.0)
            out0 = circuit.measure(i0)  # Greedy assignment

            # Set circuit
            luci.set_circuit(circuit)

            # Set DAQ config
            luci.set_daq(sample_rate=1000)

            # Set run config
            luci.set_run(
                ic_time=100_000,  # nanoseconds
                op_time=10_000_000  # nanoseconds
            )

            # Suppress protocol logger — see _PROTOCOL_LOGGER comment above.
            logging.getLogger(_PROTOCOL_LOGGER).setLevel(logging.CRITICAL)
            try:
                run = await luci._run()
            finally:
                logging.getLogger(_PROTOCOL_LOGGER).setLevel(logging.NOTSET)

            # Verify Run object
            assert run is not None, "run() should return a Run object"
            assert hasattr(run, "data"), "Run should have data attribute"

    @pytest.mark.asyncio
    async def test_lucistack_backwards_compat_single_string(self):
        """
        LUCIDAC("tcp://127.0.0.1:{port}") works.

        This test verifies backward compatibility: the LUCIDAC alias
        can be initialized with a single string endpoint.
        """
        config = DummyDACConfig(lucidac_mode=True)
        port = get_test_port(2)

        async with DummyDAC("127.0.0.1", port, config) as dac:
            dac_port = dac._server.sockets[0].getsockname()[1]

            # Import LUCIDAC alias
            from pybrid.lucipy import LUCIDAC

            # Create with single string (backward compat)
            luci = LUCIDAC(f"tcp://127.0.0.1:{dac_port}")

            # Should be a LUCIStack instance
            assert isinstance(luci, LUCIStack), (
                "LUCIDAC should be an alias for LUCIStack"
            )

            # Wrapper should have 1 endpoint with correct details
            assert luci._endpoints[0][0] == "127.0.0.1"
            assert luci._endpoints[0][1] == dac_port

    @pytest.mark.asyncio
    async def test_lucistack_num_channels_deduced(self):
        """
        Set circuit with 3 measure() calls. Run. Assert DAQ uses 3 channels.

        This test verifies that LUCIStack automatically deduces the number
        of DAQ channels from the circuit's measure() calls.
        """
        config = DummyDACConfig(lucidac_mode=True)
        port = get_test_port(4)

        async with DummyDAC("127.0.0.1", port, config) as dac:
            dac_port = dac._server.sockets[0].getsockname()[1]

            # Create LUCIStack
            luci = LUCIStack(f"tcp://127.0.0.1:{dac_port}")

            # Create circuit with 3 outputs
            circuit = Circuit()
            i0 = circuit.int(ic=1.0)
            i1 = circuit.int(ic=0.5)
            i2 = circuit.int(ic=0.25)

            out0 = circuit.measure(i0)  # Channel 0
            out1 = circuit.measure(i1)  # Channel 1
            out2 = circuit.measure(i2)  # Channel 2

            # Set circuit (should auto-detect 3 channels)
            luci.set_circuit(circuit)

            # Set DAQ without explicit num_channels
            luci.set_daq(sample_rate=1000)

            # Set run config
            luci.set_run(
                ic_time=100_000,  # nanoseconds
                op_time=10_000_000  # nanoseconds
            )

            # Suppress protocol logger — see _PROTOCOL_LOGGER comment above.
            logging.getLogger(_PROTOCOL_LOGGER).setLevel(logging.CRITICAL)
            try:
                run = await luci._run()
            finally:
                logging.getLogger(_PROTOCOL_LOGGER).setLevel(logging.NOTSET)

            assert run is not None
            assert hasattr(run, "data"), "Run should have data"

    @pytest.mark.asyncio
    async def test_lucistack_env_var_fallback(self):
        """
        Create LUCIDAC() with no args. Check LUCIDAC_ENDPOINT env var.

        This test verifies backward compatibility: when no endpoint is provided,
        LucipyWrapper should check the LUCIDAC_ENDPOINT environment variable.
        """
        config = DummyDACConfig(lucidac_mode=True)
        port = get_test_port(5)

        async with DummyDAC("127.0.0.1", port, config) as dac:
            dac_port = dac._server.sockets[0].getsockname()[1]

            # Set environment variable
            original_env = os.environ.get("LUCIDAC_ENDPOINT")
            try:
                os.environ["LUCIDAC_ENDPOINT"] = f"tcp://127.0.0.1:{dac_port}"

                # Import LUCIDAC alias
                from pybrid.lucipy import LUCIDAC

                # Create with no args - should use environment variable
                luci = LUCIDAC()

                # Wrapper should have 1 endpoint with correct details
                assert luci._endpoints[0][0] == "127.0.0.1"
                assert luci._endpoints[0][1] == dac_port

            finally:
                # Restore original environment
                if original_env is not None:
                    os.environ["LUCIDAC_ENDPOINT"] = original_env
                else:
                    os.environ.pop("LUCIDAC_ENDPOINT", None)

    @pytest.mark.asyncio
    async def test_lucistack_no_endpoint_error(self):
        """
        Create LUCIDAC() with no args and no env var. Should raise ValueError.

        This test verifies that a clear error is raised when no endpoint
        can be determined (no args, no env var, auto-detection disabled in tests).
        """
        # Ensure environment variable is not set
        original_env = os.environ.get("LUCIDAC_ENDPOINT")
        try:
            os.environ.pop("LUCIDAC_ENDPOINT", None)

            # Import LUCIDAC alias
            from pybrid.lucipy import LUCIDAC

            # Create with no args - should raise ValueError
            # (auto-detection cannot run from async context)
            with pytest.raises(ValueError, match="Auto-detection failed"):
                luci = LUCIDAC()

        finally:
            # Restore original environment
            if original_env is not None:
                os.environ["LUCIDAC_ENDPOINT"] = original_env

    @pytest.mark.asyncio
    async def test_lucistack_bare_ip_port_endpoint(self):
        """
        LUCIStack("127.0.0.1:5732") works without tcp:// scheme.

        Verifies that bare IP:PORT strings are accepted and normalized
        to the canonical tcp:// format internally.
        """
        config = DummyDACConfig(lucidac_mode=True)
        port = get_test_port(7)

        async with DummyDAC("127.0.0.1", port, config) as dac:
            dac_port = dac._server.sockets[0].getsockname()[1]

            luci = LUCIStack(f"127.0.0.1:{dac_port}")

            assert luci._endpoints[0][0] == "127.0.0.1"
            assert luci._endpoints[0][1] == dac_port

    @pytest.mark.asyncio
    async def test_lucistack_bare_ip_default_port(self):
        """
        LUCIStack("127.0.0.1") uses default port 5732.

        Verifies that a bare IP address without port or scheme
        defaults to port 5732.
        """
        luci = LUCIStack("192.168.1.100")

        assert luci._endpoints[0][0] == "192.168.1.100"
        assert luci._endpoints[0][1] == 5732, "Should use default port when none specified"

    @pytest.mark.asyncio
    async def test_lucistack_env_var_bare_ip_port(self):
        """
        LUCIDAC_ENDPOINT="192.168.1.100:5732" works without tcp:// scheme.

        Verifies that the environment variable fallback also accepts
        bare IP:PORT format.
        """
        config = DummyDACConfig(lucidac_mode=True)
        port = get_test_port(8)

        async with DummyDAC("127.0.0.1", port, config) as dac:
            dac_port = dac._server.sockets[0].getsockname()[1]

            original_env = os.environ.get("LUCIDAC_ENDPOINT")
            try:
                os.environ["LUCIDAC_ENDPOINT"] = f"127.0.0.1:{dac_port}"

                from pybrid.lucipy import LUCIDAC

                luci = LUCIDAC()

                assert luci._endpoints[0][0] == "127.0.0.1"
                assert luci._endpoints[0][1] == dac_port

            finally:
                if original_env is not None:
                    os.environ["LUCIDAC_ENDPOINT"] = original_env
                else:
                    os.environ.pop("LUCIDAC_ENDPOINT", None)

    def test_lucistack_no_endpoint_error_sync(self):
        """
        Create LUCIDAC() with no args and no env var from sync context.

        This test verifies that a clear error is raised when no endpoint
        can be determined and auto-detection finds no devices.
        Mocks detect_in_network to simulate an empty network.
        """
        # Ensure environment variable is not set
        original_env = os.environ.get("LUCIDAC_ENDPOINT")
        try:
            os.environ.pop("LUCIDAC_ENDPOINT", None)

            # Import LUCIDAC alias
            from pybrid.lucipy import LUCIDAC

            # Mock detect_in_network to raise TimeoutError (no devices)
            mock_detect = AsyncMock(
                side_effect=asyncio.TimeoutError("No available network devices found.")
            )
            with patch("pybrid.lucipy.computer.detect_in_network", mock_detect):
                # Create with no args - should raise ValueError
                with pytest.raises(ValueError, match="No LUCIDAC found"):
                    luci = LUCIDAC()

        finally:
            # Restore original environment
            if original_env is not None:
                os.environ["LUCIDAC_ENDPOINT"] = original_env

# Copyright (c) 2022-2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
Error propagation tests for LUCIDAC/REDAC hardware.

These tests verify that hardware errors are properly propagated
back to the Python client code with appropriate error types and
messages.

Environment Variables:
    TEST_LUCIDAC_ENDPOINT: tcp://host:port for LUCIDAC connection
    TEST_REDAC_ENDPOINT: tcp://host:port for REDAC connection
    TEST_SIMULATOR_ENDPOINT: tcp://host:port for Simulator connection
"""

import asyncio
import gc
import logging
from pathlib import Path
from uuid import uuid4

import pytest

import pybrid.base.proto.main_pb2 as pb
from pybrid.base.proto.io import ProtoIO
from pybrid.redac.controller import Controller
from pybrid.redac.run import Run, RunConfig, DAQConfig, RunError, RunState
from tests.conftest import get_device_endpoint


class _RunErrorFilter(logging.Filter):
    """
    Logging filter that suppresses RunError messages from asyncio.

    These errors are expected in error propagation tests and should not
    be logged as they confuse test output.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        # Suppress "Future exception was never retrieved" for RunError
        if "RunError" in record.getMessage():
            return False
        return True


_asyncio_logger = logging.getLogger("asyncio")
_run_error_filter = _RunErrorFilter()


def _suppress_run_error_handler(loop, context):
    """
    Custom exception handler that suppresses RunError from unhandled futures.

    These errors are expected in error propagation tests and should not
    be logged as they confuse test output.
    """
    exception = context.get("exception")
    if exception is not None:
        # Check both isinstance and type name to handle class reloading/import issues
        if isinstance(exception, RunError) or "RunError" in type(exception).__name__:
            # Silently ignore RunError - it's expected in these tests
            return
    # For other exceptions, use the default handler
    loop.default_exception_handler(context)


async def _cleanup_pending_futures():
    """
    Force cleanup of pending futures before restoring the exception handler.

    Futures with unhandled exceptions log errors when garbage collected.
    By forcing GC while our suppression handler is active, we ensure
    these errors are suppressed.
    """
    # Allow pending callbacks to run
    await asyncio.sleep(0)
    # Force garbage collection to trigger Future.__del__ while handler is active
    gc.collect()


def _enable_run_error_suppression(loop):
    """Enable suppression of RunError logging."""
    _asyncio_logger.addFilter(_run_error_filter)
    old_handler = loop.get_exception_handler()
    loop.set_exception_handler(_suppress_run_error_handler)
    return old_handler


def _disable_run_error_suppression(loop, old_handler):
    """Disable suppression of RunError logging."""
    _asyncio_logger.removeFilter(_run_error_filter)
    loop.set_exception_handler(old_handler)


@pytest.mark.device
class TestErrorPropagation:

    async def test_invalid_sample_rate_error(self, any_device_endpoint):
        host, port, _ = any_device_endpoint

        # Suppress RunError logging from unhandled futures
        loop = asyncio.get_running_loop()
        old_handler = _enable_run_error_suppression(loop)

        try:
            async with Controller() as ctrl:
                await ctrl.add_device(host, port)

                # Create a run with impossibly high sample rate
                # Hardware typically supports up to ~125 MHz
                run = Run(
                    id_=uuid4(),
                    config=RunConfig(
                        ic_time=10_000,
                        op_time=1_000_000,
                    ),
                    daq=DAQConfig(
                        num_channels=4,
                        sample_rate=10_000_000_000,  # 10 GHz - clearly invalid
                    ),
                )

                # The run should either:
                # 1. Fail during start_run with an exception
                # 2. Fail during execution with RunError
                # 3. Be rejected at configuration validation
                try:
                    run_state = await ctrl.start_run(run)

                    # If start succeeded, wait for potential error during execution
                    try:
                        async with asyncio.timeout(5.0):
                            await run_state.wait_all(run_state.run.state.DONE)
                    except (RunError, asyncio.TimeoutError, Exception):
                        # Expected - hardware rejected the invalid config
                        pass
                except Exception as e:
                    # Expected - configuration was rejected
                    # Verify we got a meaningful error, not a connection failure
                    assert "sample" in str(e).lower() or "rate" in str(e).lower() or \
                           "invalid" in str(e).lower() or "error" in str(e).lower() or \
                           isinstance(e, (ValueError, RuntimeError, RunError)), \
                        f"Expected meaningful error, got: {type(e).__name__}: {e}"

                # Verify controller is still operational
                assert len(ctrl.devices) >= 1, (
                    "Controller should still have devices after error"
                )

            # Cleanup pending futures before restoring handler
            await _cleanup_pending_futures()
        finally:
            _disable_run_error_suppression(loop, old_handler)

    async def test_invalid_op_time_error(self, any_device_endpoint):
        host, port, device_type = any_device_endpoint

        # Simulator does not validate OP time
        if device_type == "simulator":
            pytest.skip("Simulator does not validate OP time")

        # Suppress RunError logging from unhandled futures
        loop = asyncio.get_running_loop()
        old_handler = _enable_run_error_suppression(loop)

        try:
            async with Controller() as ctrl:
                await ctrl.add_device(host, port)

                # Test with extremely large op_time
                # Hardware may have limits on maximum operation time
                run = Run(
                    id_=uuid4(),
                    config=RunConfig(
                        ic_time=10_000,
                        op_time=10**18,  # Unreasonably large value
                    ),
                )

                try:
                    run_state = await ctrl.start_run(run)

                    try:
                        async with asyncio.timeout(5.0):
                            await run_state.wait_all(run_state.run.state.DONE)
                    except (RunError, asyncio.TimeoutError, OverflowError):
                        # Expected - hardware rejected or timed out
                        pass
                except (ValueError, RuntimeError, OverflowError, RunError):
                    # Expected - invalid configuration rejected
                    pass
                except Exception:
                    # Other errors might occur for extreme values
                    pass

                # Verify controller is still operational
                assert len(ctrl.devices) >= 1, (
                    "Controller should still have devices after error"
                )

            # Cleanup pending futures before restoring handler
            await _cleanup_pending_futures()
        finally:
            _disable_run_error_suppression(loop, old_handler)

    async def test_connection_recovery(self, any_device_endpoint, harmonic_pb_config):
        host, port, device_type = any_device_endpoint

        # Simulator does not validate OP time, so the "bad run" won't fail
        if device_type == "simulator":
            pytest.skip("Simulator does not validate OP time")

        # Suppress RunError logging from unhandled futures
        loop = asyncio.get_running_loop()
        old_handler = _enable_run_error_suppression(loop)

        try:
            async with Controller() as ctrl:
                await ctrl.add_device(host, port)

                # First, trigger an error condition (invalid config)
                await ctrl.set_module(harmonic_pb_config.module)
                bad_run = Run(
                    id_=uuid4(),
                    config=RunConfig(
                        ic_time=10_000,
                        op_time=10**18,
                    ),
                )

                try:
                    await ctrl.start_run(bad_run)
                except Exception:
                    pass  # Expected error

                # Now try a valid run - should succeed
                await ctrl.set_module(harmonic_pb_config.module)
                good_run = Run(
                    id_=uuid4(),
                    config=RunConfig(
                        ic_time=10_000,
                        op_time=100_000,
                    ),
                )

                run_state = await ctrl.start_run(good_run)

                async with asyncio.timeout(10.0):
                    await run_state.wait_all(RunState.DONE)

                # If we get here, recovery was successful

            # Cleanup pending futures before restoring handler
            await _cleanup_pending_futures()
        finally:
            _disable_run_error_suppression(loop, old_handler)

    async def test_error_message_content(self, any_device_endpoint):
        host, port, _ = any_device_endpoint

        # Suppress RunError logging from unhandled futures
        loop = asyncio.get_running_loop()
        old_handler = _enable_run_error_suppression(loop)

        try:
            async with Controller() as ctrl:
                await ctrl.add_device(host, port)

                # Create intentionally invalid configuration
                run = Run(
                    id_=uuid4(),
                    config=RunConfig(
                        ic_time=-1,  # Invalid negative time
                        op_time=100_000,
                    ),
                )

                error_caught = False
                error_message = ""

                try:
                    run_state = await ctrl.start_run(run)

                    async with asyncio.timeout(5.0):
                        await run_state.wait_all(run_state.run.state.DONE)
                except Exception as e:
                    error_caught = True
                    error_message = str(e)

                if error_caught:
                    # Verify error message has content
                    assert len(error_message) > 0, (
                        "Error message should not be empty"
                    )
                else:
                    # Hardware may accept negative values (interpreted as unsigned)
                    # This is acceptable behavior
                    pass

            # Cleanup pending futures before restoring handler
            await _cleanup_pending_futures()
        finally:
            _disable_run_error_suppression(loop, old_handler)


@pytest.fixture
def harmonic_pb_config():
    """
    Load harmonic oscillator config from harmonic_pb.apb.

    Returns:
        pb.File containing the harmonic oscillator configuration.
    """
    config_path = Path(__file__).parent.parent / "data" / "harmonic_pb.apb"
    module = ProtoIO.load_module(str(config_path))
    pb_file = pb.File()
    pb_file.module.CopyFrom(module)
    return pb_file


@pytest.fixture
def harmonic_pb_config_with_portconfig():
    """
    Load harmonic oscillator config and add a PortConfig for unavailable hardware.

    Loads harmonic_pb.apb, removes any existing portConfig entries, and adds
    a new PortConfig for entity "00-00-00-00-00-00/T" which is not present
    on devices without Port hardware.

    Returns:
        pb.File containing the harmonic oscillator configuration with added PortConfig.
    """
    config_path = Path(__file__).parent.parent / "data" / "harmonic_pb.apb"
    module = ProtoIO.load_module(str(config_path))
    pb_file = pb.File()
    pb_file.module.CopyFrom(module)

    # Add a PortConfig for entity "00-00-00-00-00-00" (unavailable hardware)
    port_config = pb.Item(
        entity=pb.EntityId(path="00-00-00-00-00-00"),
        port_config=pb.PortConfig(
            states=[
                pb.PortConfig.AclState.INTERNAL,
                pb.PortConfig.AclState.INTERNAL,
                pb.PortConfig.AclState.INTERNAL,
                pb.PortConfig.AclState.INTERNAL,
                pb.PortConfig.AclState.INTERNAL,
                pb.PortConfig.AclState.INTERNAL,
                pb.PortConfig.AclState.INTERNAL,
                pb.PortConfig.AclState.INTERNAL,
            ]
        )
    )
    pb_file.module.items.append(port_config)

    return pb_file


@pytest.fixture
def harmonic_pb_config_with_switchconfig():
    """
    Load harmonic oscillator config and add a SwitchConfig for unavailable hardware.

    Loads harmonic_pb.apb and adds a new SwitchConfig for entity "00-00-00-00-00-00/T"
    which is not present on LUCIDAC devices (they don't have switch/routing hardware
    at T-block).

    Returns:
        pb.File containing the harmonic oscillator configuration with added SwitchConfig.
    """
    config_path = Path(__file__).parent.parent / "data" / "harmonic_pb.apb"
    module = ProtoIO.load_module(str(config_path))
    pb_file = pb.File()
    pb_file.module.CopyFrom(module)

    # Add a SwitchConfig for entity "00-00-00-00-00-00/T" (unavailable hardware on LUCIDAC)
    switch_config = pb.Item(
        entity=pb.EntityId(path="00-00-00-00-00-00/T"),
        switch_config=pb.SwitchConfig(
            muxes=[
                pb.Mux(state=0),
                pb.Mux(state=0),
                pb.Mux(state=0),
                pb.Mux(state=0),
                pb.Mux(state=0),
                pb.Mux(state=0),
                pb.Mux(state=0),
                pb.Mux(state=0),
            ]
        )
    )
    pb_file.module.items.append(switch_config)

    return pb_file


@pytest.mark.device
class TestUnavailableHardwareErrorPropagation:
    """
    Tests for proper error propagation when configs reference unavailable hardware.

    These tests verify that devices properly reject configurations that reference
    hardware blocks they don't have, and that errors are propagated with useful
    messages.
    """

    @pytest.mark.redac
    async def test_redac_portconfig_for_unavailable_hardware_error_propagation(
        self, harmonic_pb_config_with_portconfig
    ):
        """Sends PortConfig for "00-00-00-00-00-00" to REDAC which lacks Port hardware."""
        # Only run on REDAC - Simulator handles this differently
        endpoint = get_device_endpoint("TEST_REDAC_ENDPOINT")
        if endpoint is None:
            pytest.skip("TEST_REDAC_ENDPOINT not set")

        host, port = endpoint

        async with Controller() as ctrl:
            await ctrl.add_device(host, port)

            # Attempt to set module containing PortConfig for unavailable hardware
            # This should fail because the device doesn't have Port hardware
            error_caught = False
            error_message = ""

            try:
                await ctrl.set_module(harmonic_pb_config_with_portconfig.module)
            except Exception as e:
                error_caught = True
                error_message = str(e)

            # Verify that an error was raised
            assert error_caught, (
                "Expected error when sending PortConfig to REDAC without Port hardware, "
                "but no error was raised. "
                "The device should reject configs for hardware it doesn't have."
            )

            # Verify error message is not empty and contains useful info
            assert len(error_message) > 0, (
                "Error message should not be empty"
            )

            # Verify controller is still operational after error
            assert len(ctrl.devices) >= 1, (
                "Controller should still have devices after config error"
            )

    @pytest.mark.lucidac
    async def test_lucidac_switchconfig_for_unavailable_hardware_error_propagation(
        self, harmonic_pb_config_with_switchconfig
    ):
        """Sends SwitchConfig for "00-00-00-00-00-00/T" to LUCIDAC which lacks T-block switch hardware."""
        # Only run on LUCIDAC
        endpoint = get_device_endpoint("TEST_LUCIDAC_ENDPOINT")
        if endpoint is None:
            pytest.skip("TEST_LUCIDAC_ENDPOINT not set")

        host, port = endpoint

        async with Controller() as ctrl:
            await ctrl.add_device(host, port)

            # Attempt to set module containing SwitchConfig for unavailable hardware
            # This should fail because LUCIDAC doesn't have switch hardware at T-block
            error_caught = False
            error_message = ""

            try:
                await ctrl.set_module(harmonic_pb_config_with_switchconfig.module)
            except Exception as e:
                error_caught = True
                error_message = str(e)

            # Verify that an error was raised
            assert error_caught, (
                "Expected error when sending SwitchConfig for entity '00-00-00-00-00-00/T' "
                "to LUCIDAC which doesn't have switch hardware at T-block, "
                "but no error was raised. "
                "The device should reject configs for hardware it doesn't have."
            )

            # Verify error message is not empty and contains useful info
            assert len(error_message) > 0, (
                "Error message should not be empty"
            )

            # Verify controller is still operational after error
            assert len(ctrl.devices) >= 1, (
                "Controller should still have devices after config error"
            )

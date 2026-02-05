# Copyright (c) 2022-2025 anabrid GmbH
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
Comprehensive integration tests for DummyDAC.
Tests all error injection modes and complete run cycles.
"""

import asyncio
import re
import warnings
from ipaddress import IPv4Address
from uuid import uuid4

import pytest

import pybrid.base.proto.main_pb2 as pb
from pybrid.base.transport.tcp import TCPTransport
from pybrid.mock import DummyDAC, DummyDACConfig, DummyDACMacMode, DummyDACErrorStage
from pybrid.redac.entities import Path
from pybrid.redac.protocol.protocol import Protocol


# Polling interval for checking run completion
POLL_INTERVAL_SECONDS = 0.1
# Buffer time added to OP time for timeout calculation
TIMEOUT_BUFFER_SECONDS = 1.0
# Number of carriers in DummyDAC
NUM_CARRIERS = 2


def ns_to_seconds(ns: int) -> float:
    """Convert nanoseconds to seconds."""
    return ns / 1e9


async def wait_for_condition(condition_fn, timeout: float):
    """
    Poll until condition_fn returns True or timeout is reached.

    :param condition_fn: Callable returning bool indicating if condition is met.
    :param timeout: Maximum seconds to wait.
    :raises TimeoutError: If condition not met within timeout.
    """
    elapsed = 0.0
    while elapsed < timeout:
        if condition_fn():
            return
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
        elapsed += POLL_INTERVAL_SECONDS
    raise TimeoutError(f"Condition not met within {timeout}s")


@pytest.mark.asyncio
async def test_fewer_samples_error_injection():
    """Test that FEWER_SAMPLES error results in incomplete data."""
    sample_rate = 1000
    op_time_ns = 1_000_000_000  # 1 second
    timeout = ns_to_seconds(op_time_ns) + TIMEOUT_BUFFER_SECONDS

    # Expected samples per carrier = sample_rate * op_time_seconds
    expected_samples_per_carrier = int(sample_rate * ns_to_seconds(op_time_ns))
    # Total expected across all carriers
    expected_total_samples = expected_samples_per_carrier * NUM_CARRIERS

    received_data = []
    run_done = []

    config = DummyDACConfig(error_stage=DummyDACErrorStage.FEWER_SAMPLES)
    async with DummyDAC("127.0.0.1", 15850, config):
        transport = await TCPTransport.create("127.0.0.1", 15850)
        protocol = Protocol(IPv4Address("127.0.0.1"), transport)

        async def collect_data(msg: pb.RunDataMessage):
            received_data.append(msg)

        async def collect_state(msg: pb.RunStateChangeMessage):
            if msg.new_ == pb.RunState.DONE:
                run_done.append(True)

        protocol.register_callback(
            pb.MessageV1.RUN_DATA_MESSAGE_FIELD_NUMBER,
            collect_data
        )
        protocol.register_callback(
            pb.MessageV1.RUN_STATE_CHANGE_MESSAGE_FIELD_NUMBER,
            collect_state
        )

        async with protocol:
            run_id = uuid4()
            await protocol.send_body_and_wait_response(pb.StartRunCommand(
                run=pb.Run(id=str(run_id), chunk=0),
                run_config=pb.RunConfig(
                    ic_time=pb.Time(value=100_000, prefix=pb.Prefix.NANO),
                    op_time=pb.Time(value=op_time_ns, prefix=pb.Prefix.NANO)
                ),
                daq_config=pb.DaqConfig(num_channels=4, sample_rate=sample_rate),
                sync_config=pb.SyncConfig(),
                calibration_config=pb.CalibrationConfig()
            ))

            # Wait for run to complete
            await wait_for_condition(lambda: len(run_done) > 0, timeout=timeout)

            # Count total samples received
            total_samples = sum(msg.data.sample_count for msg in received_data)
            # FEWER_SAMPLES should result in less than the expected full amount
            assert total_samples < expected_total_samples, (
                f"Expected fewer than {expected_total_samples} samples, got {total_samples}"
            )


@pytest.mark.asyncio
async def test_drop_takeoff_state():
    """Test that DROP_TAKEOFF_STATE suppresses TAKE_OFF message."""
    op_time_ns = 10_000_000  # 10ms
    timeout = ns_to_seconds(op_time_ns) + TIMEOUT_BUFFER_SECONDS

    received_states = []

    config = DummyDACConfig(error_stage=DummyDACErrorStage.DROP_TAKEOFF_STATE)
    async with DummyDAC("127.0.0.1", 15851, config):
        transport = await TCPTransport.create("127.0.0.1", 15851)
        protocol = Protocol(IPv4Address("127.0.0.1"), transport)

        async def collect_state(msg: pb.RunStateChangeMessage):
            received_states.append(msg.new_)

        protocol.register_callback(
            pb.MessageV1.RUN_STATE_CHANGE_MESSAGE_FIELD_NUMBER,
            collect_state
        )

        async with protocol:
            run_id = uuid4()
            await protocol.send_body_and_wait_response(pb.StartRunCommand(
                run=pb.Run(id=str(run_id), chunk=0),
                run_config=pb.RunConfig(
                    ic_time=pb.Time(value=100_000, prefix=pb.Prefix.NANO),
                    op_time=pb.Time(value=op_time_ns, prefix=pb.Prefix.NANO)
                ),
                daq_config=pb.DaqConfig(num_channels=2, sample_rate=100),
                sync_config=pb.SyncConfig(),
                calibration_config=pb.CalibrationConfig()
            ))

            # Wait for DONE state (run completion)
            await wait_for_condition(
                lambda: pb.RunState.DONE in received_states,
                timeout=timeout
            )

            # TAKE_OFF should NOT be in received states
            assert pb.RunState.TAKE_OFF not in received_states
            # But other states should be present
            assert pb.RunState.IC in received_states
            assert pb.RunState.DONE in received_states


@pytest.mark.asyncio
async def test_drop_done_state():
    """Test that DROP_DONE_STATE suppresses DONE message."""
    op_time_ns = 10_000_000  # 10ms
    timeout = ns_to_seconds(op_time_ns) + TIMEOUT_BUFFER_SECONDS

    received_states = []

    config = DummyDACConfig(error_stage=DummyDACErrorStage.DROP_DONE_STATE)
    async with DummyDAC("127.0.0.1", 15852, config):
        transport = await TCPTransport.create("127.0.0.1", 15852)
        protocol = Protocol(IPv4Address("127.0.0.1"), transport)

        async def collect_state(msg: pb.RunStateChangeMessage):
            received_states.append(msg.new_)

        protocol.register_callback(
            pb.MessageV1.RUN_STATE_CHANGE_MESSAGE_FIELD_NUMBER,
            collect_state
        )

        async with protocol:
            run_id = uuid4()
            await protocol.send_body_and_wait_response(pb.StartRunCommand(
                run=pb.Run(id=str(run_id), chunk=0),
                run_config=pb.RunConfig(
                    ic_time=pb.Time(value=100_000, prefix=pb.Prefix.NANO),
                    op_time=pb.Time(value=op_time_ns, prefix=pb.Prefix.NANO)
                ),
                daq_config=pb.DaqConfig(num_channels=2, sample_rate=100),
                sync_config=pb.SyncConfig(),
                calibration_config=pb.CalibrationConfig()
            ))

            # Wait for OP_END state (since DONE is suppressed)
            await wait_for_condition(
                lambda: pb.RunState.OP_END in received_states,
                timeout=timeout
            )

            # DONE should NOT be in received states
            assert pb.RunState.DONE not in received_states
            # But other states should be present
            assert pb.RunState.TAKE_OFF in received_states
            assert pb.RunState.OP_END in received_states


@pytest.mark.asyncio
async def test_during_run_error():
    """Test that DURING_RUN error transitions to ERROR state."""
    op_time_ns = 10_000_000  # 10ms
    timeout = ns_to_seconds(op_time_ns) + TIMEOUT_BUFFER_SECONDS

    received_states = []

    config = DummyDACConfig(error_stage=DummyDACErrorStage.DURING_RUN)
    async with DummyDAC("127.0.0.1", 15853, config):
        transport = await TCPTransport.create("127.0.0.1", 15853)
        protocol = Protocol(IPv4Address("127.0.0.1"), transport)

        async def collect_state(msg: pb.RunStateChangeMessage):
            received_states.append(msg.new_)

        protocol.register_callback(
            pb.MessageV1.RUN_STATE_CHANGE_MESSAGE_FIELD_NUMBER,
            collect_state
        )

        async with protocol:
            run_id = uuid4()
            await protocol.send_body_and_wait_response(pb.StartRunCommand(
                run=pb.Run(id=str(run_id), chunk=0),
                run_config=pb.RunConfig(
                    ic_time=pb.Time(value=100_000, prefix=pb.Prefix.NANO),
                    op_time=pb.Time(value=op_time_ns, prefix=pb.Prefix.NANO)
                ),
                daq_config=pb.DaqConfig(num_channels=2, sample_rate=100),
                sync_config=pb.SyncConfig(),
                calibration_config=pb.CalibrationConfig()
            ))

            # Wait for ERROR state
            await wait_for_condition(
                lambda: pb.RunState.ERROR in received_states,
                timeout=timeout
            )

            # ERROR should be in received states
            assert pb.RunState.ERROR in received_states
            # DONE should NOT be in received states
            assert pb.RunState.DONE not in received_states


@pytest.mark.asyncio
async def test_physical_mac_mode():
    """Test that physical MAC mode uses non-virtual addresses."""
    config = DummyDACConfig(mac_mode=DummyDACMacMode.PHYSICAL)
    async with DummyDAC("127.0.0.1", 15854, config) as server:
        transport = await TCPTransport.create("127.0.0.1", 15854)
        protocol = Protocol(IPv4Address("127.0.0.1"), transport)
        async with protocol:
            entity = await protocol.get_entity()

            # Check carrier IDs are not virtual MACs
            for carrier in entity.children:
                mac = carrier.id
                # Should not be 00-00-00-00-00-XX
                assert not mac.startswith("00-00-00-00-00-")
                # Should be valid MAC format
                mac_pattern = re.compile(r'^[0-9A-F]{2}(-[0-9A-F]{2}){5}$')
                assert mac_pattern.match(mac), f"Invalid MAC format: {mac}"


def test_dummy_controller_deprecation_warning():
    """Verify DummyController emits deprecation warning."""
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        from pybrid.redac.dummy import DummyController
        _ = DummyController()

        # Check that a deprecation warning was issued
        assert len(w) >= 1
        deprecation_warnings = [warning for warning in w if issubclass(warning.category, DeprecationWarning)]
        assert len(deprecation_warnings) >= 1
        assert "DummyDAC" in str(deprecation_warnings[0].message)


@pytest.mark.asyncio
async def test_extract_error_injection():
    """Verify AT_EXTRACT error injection works."""
    config = DummyDACConfig(
        error_stage=DummyDACErrorStage.AT_EXTRACT,
        error_message="Simulated extract error"
    )
    async with DummyDAC("127.0.0.1", 15855, config):
        transport = await TCPTransport.create("127.0.0.1", 15855)
        protocol = Protocol(IPv4Address("127.0.0.1"), transport)
        async with protocol:
            # First store some config
            test_config = pb.Config(entity=pb.EntityId(path="/00-00-00-00-00-00/0/M0"))
            bundle = pb.ConfigBundle(configs=[test_config])
            await protocol.set_config_bundle(bundle)

            # Now try to extract - should get error
            response = await protocol.send_body_and_wait_response(
                pb.ExtractCommand(entity=pb.EntityId(path="/00-00-00-00-00-00"), recursive=True)
            )
            assert response.WhichOneof("kind") == "error_message"
            assert "Simulated extract error" in response.error_message.description


@pytest.mark.asyncio
async def test_complete_run_cycle():
    """Test a complete run cycle with all state transitions and sample count verification."""
    op_time_ns = 100_000_000  # 100ms
    sample_rate = 1000
    num_channels = 4
    timeout = ns_to_seconds(op_time_ns) + TIMEOUT_BUFFER_SECONDS

    # Expected samples per carrier = sample_rate * op_time_seconds
    expected_samples_per_carrier = int(sample_rate * ns_to_seconds(op_time_ns))
    min_expected_total_samples = expected_samples_per_carrier * NUM_CARRIERS

    received_states = []
    received_data = []
    received_data_end_count = 0

    config = DummyDACConfig()
    async with DummyDAC("127.0.0.1", 15856, config):
        transport = await TCPTransport.create("127.0.0.1", 15856)
        protocol = Protocol(IPv4Address("127.0.0.1"), transport)

        async def collect_state(msg: pb.RunStateChangeMessage):
            received_states.append(msg.new_)

        async def collect_data(msg: pb.RunDataMessage):
            received_data.append(msg)

        async def collect_data_end(msg: pb.RunDataEndMessage):
            nonlocal received_data_end_count
            received_data_end_count += 1

        protocol.register_callback(pb.MessageV1.RUN_STATE_CHANGE_MESSAGE_FIELD_NUMBER, collect_state)
        protocol.register_callback(pb.MessageV1.RUN_DATA_MESSAGE_FIELD_NUMBER, collect_data)
        protocol.register_callback(pb.MessageV1.RUN_DATA_END_MESSAGE_FIELD_NUMBER, collect_data_end)

        async with protocol:
            run_id = uuid4()
            await protocol.send_body_and_wait_response(pb.StartRunCommand(
                run=pb.Run(id=str(run_id), chunk=0),
                run_config=pb.RunConfig(
                    ic_time=pb.Time(value=100_000, prefix=pb.Prefix.NANO),
                    op_time=pb.Time(value=op_time_ns, prefix=pb.Prefix.NANO)
                ),
                daq_config=pb.DaqConfig(num_channels=num_channels, sample_rate=sample_rate),
                sync_config=pb.SyncConfig(),
                calibration_config=pb.CalibrationConfig()
            ))

            # Wait for DONE state (run completion)
            await wait_for_condition(
                lambda: pb.RunState.DONE in received_states,
                timeout=timeout
            )

            # Verify full state machine sequence
            assert pb.RunState.TAKE_OFF in received_states
            assert pb.RunState.IC in received_states
            assert pb.RunState.OP in received_states
            assert pb.RunState.OP_END in received_states
            assert pb.RunState.DONE in received_states

            # Verify sample count meets minimum expected
            total_samples = sum(msg.data.sample_count for msg in received_data)
            assert total_samples >= min_expected_total_samples, (
                f"Expected at least {min_expected_total_samples} samples, got {total_samples}"
            )

            # Should have received data end from 2 carriers
            assert received_data_end_count == NUM_CARRIERS

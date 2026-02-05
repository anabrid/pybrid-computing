# Copyright (c) 2022-2025 anabrid GmbH
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""Tests for the DummyDAC run execution and sample generation."""

import asyncio
from ipaddress import IPv4Address
from uuid import uuid4

import pytest

import pybrid.base.proto.main_pb2 as pb
from pybrid.base.transport.tcp import TCPTransport
from pybrid.mock import DummyDAC, DummyDACConfig, DummyDACErrorStage
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
async def test_run_returns_success():
    """Verify run command returns success response."""
    config = DummyDACConfig()
    async with DummyDAC("127.0.0.1", 15820, config):
        transport = await TCPTransport.create("127.0.0.1", 15820)
        protocol = Protocol(IPv4Address("127.0.0.1"), transport)
        async with protocol:
            run_id = uuid4()
            response = await protocol.send_body_and_wait_response(pb.StartRunCommand(
                run=pb.Run(id=str(run_id), chunk=0),
                run_config=pb.RunConfig(
                    ic_time=pb.Time(value=100_000, prefix=pb.Prefix.NANO),
                    op_time=pb.Time(value=10_000_000, prefix=pb.Prefix.NANO)
                ),
                daq_config=pb.DaqConfig(num_channels=4, sample_rate=1000),
                sync_config=pb.SyncConfig(),
                calibration_config=pb.CalibrationConfig()
            ))
            assert response.WhichOneof("kind") == "start_run_response"


@pytest.mark.asyncio
async def test_start_run_error_injection():
    """Verify AT_START_RUN error injection works."""
    config = DummyDACConfig(error_stage=DummyDACErrorStage.AT_START_RUN)
    async with DummyDAC("127.0.0.1", 15821, config):
        transport = await TCPTransport.create("127.0.0.1", 15821)
        protocol = Protocol(IPv4Address("127.0.0.1"), transport)
        async with protocol:
            run_id = uuid4()
            response = await protocol.send_body_and_wait_response(pb.StartRunCommand(
                run=pb.Run(id=str(run_id), chunk=0),
                run_config=pb.RunConfig(
                    ic_time=pb.Time(value=100_000, prefix=pb.Prefix.NANO),
                    op_time=pb.Time(value=10_000_000, prefix=pb.Prefix.NANO)
                ),
                daq_config=pb.DaqConfig(num_channels=4, sample_rate=1000),
                sync_config=pb.SyncConfig(),
                calibration_config=pb.CalibrationConfig()
            ))
            assert response.WhichOneof("kind") == "error_message"


@pytest.mark.asyncio
async def test_run_state_changes_received():
    """Verify state change messages are received during run."""
    op_time_ns = 10_000_000  # 10ms
    timeout = ns_to_seconds(op_time_ns) + TIMEOUT_BUFFER_SECONDS

    received_states = []

    config = DummyDACConfig()
    async with DummyDAC("127.0.0.1", 15822, config):
        transport = await TCPTransport.create("127.0.0.1", 15822)
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

            # Wait until DONE state is received (indicates run completion)
            await wait_for_condition(
                lambda: pb.RunState.DONE in received_states,
                timeout=timeout
            )

            assert pb.RunState.TAKE_OFF in received_states
            assert pb.RunState.DONE in received_states


@pytest.mark.asyncio
async def test_run_data_messages_received():
    """Verify run data messages are received with correct sample count."""
    op_time_ns = 100_000_000  # 100ms
    sample_rate = 1000
    num_channels = 4
    timeout = ns_to_seconds(op_time_ns) + TIMEOUT_BUFFER_SECONDS

    # Expected samples per channel = sample_rate * op_time_seconds
    op_time_seconds = ns_to_seconds(op_time_ns)
    expected_samples_per_channel = int(sample_rate * op_time_seconds)
    # Total expected across all carriers (each carrier sends its own data)
    min_expected_total_samples = expected_samples_per_channel * NUM_CARRIERS

    received_data = []
    run_done = []

    config = DummyDACConfig()
    async with DummyDAC("127.0.0.1", 15823, config):
        transport = await TCPTransport.create("127.0.0.1", 15823)
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
                daq_config=pb.DaqConfig(num_channels=num_channels, sample_rate=sample_rate),
                sync_config=pb.SyncConfig(),
                calibration_config=pb.CalibrationConfig()
            ))

            # Wait for run completion
            await wait_for_condition(lambda: len(run_done) > 0, timeout=timeout)

            # Count total samples received
            total_samples = sum(msg.data.sample_count for msg in received_data)
            assert total_samples >= min_expected_total_samples, (
                f"Expected at least {min_expected_total_samples} samples, got {total_samples}"
            )


@pytest.mark.asyncio
async def test_run_data_end_uses_config_channel_count():
    """Verify RunDataEndMessage uses channel count from ConfigCommand, not DaqConfig."""
    op_time_ns = 10_000_000  # 10ms
    timeout = ns_to_seconds(op_time_ns) + TIMEOUT_BUFFER_SECONDS

    received_end_messages = []

    config = DummyDACConfig()
    async with DummyDAC("127.0.0.1", 15824, config):
        transport = await TCPTransport.create("127.0.0.1", 15824)
        protocol = Protocol(IPv4Address("127.0.0.1"), transport)

        async def collect_end_data(msg: pb.RunDataEndMessage):
            received_end_messages.append(msg)

        protocol.register_callback(
            pb.MessageV1.RUN_DATA_END_MESSAGE_FIELD_NUMBER,
            collect_end_data
        )

        async with protocol:
            # First send ConfigCommand with ADC channels
            # Configure 8 ADC channels on the first carrier
            requested_channels = 8
            adc_channels = [
                pb.AdcChannel(idx=i, gain=1.0, offset=0.0)
                for i in range(requested_channels)
            ]
            adc_config = pb.AdcConfig(channels=adc_channels)
            carrier_config = pb.Config(
                entity=pb.EntityId(path="/00-00-00-00-00-00"),
                adc_config=adc_config
            )
            bundle = pb.ConfigBundle(configs=[carrier_config])
            await protocol.set_config_bundle(bundle)

            # Now send StartRunCommand - note: DaqConfig has different channel count
            # to verify we use ConfigCommand, not DaqConfig
            run_id = uuid4()
            await protocol.send_body_and_wait_response(pb.StartRunCommand(
                run=pb.Run(id=str(run_id), chunk=0),
                run_config=pb.RunConfig(
                    ic_time=pb.Time(value=100_000, prefix=pb.Prefix.NANO),
                    op_time=pb.Time(value=op_time_ns, prefix=pb.Prefix.NANO)
                ),
                daq_config=pb.DaqConfig(num_channels=4, sample_rate=1000),  # Different from config!
                sync_config=pb.SyncConfig(),
                calibration_config=pb.CalibrationConfig()
            ))

            # Wait for both RunDataEndMessage (one per carrier)
            await wait_for_condition(
                lambda: len(received_end_messages) == NUM_CARRIERS,
                timeout=timeout
            )

            # Should receive one RunDataEndMessage per carrier (2 carriers)
            assert len(received_end_messages) == NUM_CARRIERS

            # Channel count should come from ConfigCommand (8), not DaqConfig (4)
            for msg in received_end_messages:
                assert msg.data.channel_count == requested_channels
                assert len(msg.data.scaling) == requested_channels

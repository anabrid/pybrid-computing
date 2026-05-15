# Copyright (c) 2022-2025 anabrid GmbH
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""Tests for the DummyDAC run execution and sample generation.

Uses the native C++ ControlChannel (via AsyncControlChannel) to exercise
DummyDAC over a real TCP connection — no internal Python Protocol mocking.
"""

import asyncio
from uuid import uuid4

import pytest

import pybrid.base.proto.main_pb2 as pb
from pybrid.mock import DummyDAC, DummyDACConfig, DummyDACErrorStage
from pybrid.redac.control import AsyncControlChannel

try:
    from pybrid.native._impl import ControlChannel as NativeControlChannel

    _NATIVE_AVAILABLE = True
except ImportError:
    _NATIVE_AVAILABLE = False
    NativeControlChannel = None

pytestmark = pytest.mark.skipif(
    not _NATIVE_AVAILABLE,
    reason="pybrid.native._impl.ControlChannel is not available (C++ bindings not built)",
)

LOCALHOST = "127.0.0.1"
OP_TIMEOUT = 5.0
# Short run op-time (10 ms) — keeps run lifecycle tests fast.
RUN_OP_TIME_NS = 10_000_000  # 10 ms
# Budget for the entire run including state callbacks (op-time + 2 s headroom).
RUN_TIMEOUT = RUN_OP_TIME_NS / 1e9 + 2.0
# Number of carriers in DummyDAC REDAC mode (default).
NUM_CARRIERS = 2


async def _make_channel(port: int) -> AsyncControlChannel:
    """
    Create and start an AsyncControlChannel connected to *port* on localhost.

    Args:
        port: TCP port of the target DummyDAC server.

    Returns:
        A started :class:`AsyncControlChannel`.
    """
    loop = asyncio.get_running_loop()
    native = await loop.run_in_executor(
        None,
        NativeControlChannel.create,
        LOCALHOST,
        port,
        OP_TIMEOUT,
    )
    channel = AsyncControlChannel(native)
    channel.start()
    return channel


def _make_run_command(op_time_ns: int, num_channels: int = 4, sample_rate: int = 1000) -> pb.StartRunCommand:
    """
    Build a standard StartRunCommand for testing.

    Args:
        op_time_ns:   OP phase duration in nanoseconds.
        num_channels: Number of DAQ channels.
        sample_rate:  DAQ sample rate in samples per second.

    Returns:
        A populated :class:`pb.StartRunCommand`.
    """
    return pb.StartRunCommand(
        run=pb.Run(id=str(uuid4()), chunk=0),
        run_config=pb.RunConfig(
            ic_time=pb.Time(value=100_000, prefix=pb.Prefix.NANO),
            op_time=pb.Time(value=op_time_ns, prefix=pb.Prefix.NANO),
            halt_on_overload=False,
        ),
        daq_config=pb.DaqConfig(
            num_channels=num_channels,
            sample_rate=sample_rate,
            sample_op=True,
            sample_op_end=True,
        ),
        sync_config=pb.SyncConfig(enabled=False),
    )


@pytest.mark.asyncio
async def test_start_run_error_injection():
    """AT_START_RUN error injection causes start_run_request to return a failure Result."""
    config = DummyDACConfig(error_stage=DummyDACErrorStage.AT_START_RUN)
    async with DummyDAC(LOCALHOST, 0, config) as server:
        port = server.port
        channel = await _make_channel(port)
        try:
            cmd = _make_run_command(RUN_OP_TIME_NS)
            result = await asyncio.wait_for(channel.start_run_request(cmd), timeout=OP_TIMEOUT)
            assert (
                result.ok is False
            ), "start_run_request() must return a failure Result for AT_START_RUN error injection"
        finally:
            await channel.stop()


@pytest.mark.asyncio
async def test_run_data_messages_received():
    op_time_ns = 100_000_000  # 100 ms
    sample_rate = 1000
    num_channels = 4
    run_timeout = op_time_ns / 1e9 + 2.0

    expected_samples_per_carrier = int(sample_rate * (op_time_ns / 1e9))
    min_expected_total_samples = expected_samples_per_carrier * NUM_CARRIERS

    config = DummyDACConfig()
    async with DummyDAC(LOCALHOST, 0, config) as server:
        port = server.port
        channel = await _make_channel(port)
        loop = asyncio.get_running_loop()

        data_messages: list[pb.RunDataMessage] = []
        done_event = asyncio.Event()

        def on_data(msg: pb.MessageV1) -> None:
            data_messages.append(msg.run_data_message)

        def on_state_change(msg: pb.MessageV1) -> None:
            if msg.run_state_change_message.new_ == pb.RunState.DONE:
                loop.call_soon_threadsafe(done_event.set)

        channel.register_callback(pb.MessageV1.RUN_DATA_MESSAGE_FIELD_NUMBER, on_data)
        channel.register_callback(pb.MessageV1.RUN_STATE_CHANGE_MESSAGE_FIELD_NUMBER, on_state_change)

        try:
            cmd = _make_run_command(op_time_ns, num_channels=num_channels, sample_rate=sample_rate)
            await asyncio.wait_for(channel.start_run_request(cmd), timeout=OP_TIMEOUT)
            await asyncio.wait_for(done_event.wait(), timeout=run_timeout)

            total_samples = sum(msg.data.sample_count for msg in data_messages)
            assert (
                total_samples >= min_expected_total_samples
            ), f"Expected at least {min_expected_total_samples} samples, got {total_samples}"
        finally:
            await channel.stop()


@pytest.mark.asyncio
async def test_run_data_end_uses_config_channel_count():
    op_time_ns = RUN_OP_TIME_NS
    requested_channels = 8

    config = DummyDACConfig()
    async with DummyDAC(LOCALHOST, 0, config) as server:
        port = server.port
        channel = await _make_channel(port)
        loop = asyncio.get_running_loop()

        end_messages: list[pb.RunDataEndMessage] = []
        end_event = asyncio.Event()

        def on_data_end(msg: pb.MessageV1) -> None:
            end_messages.append(msg.run_data_end_message)
            if len(end_messages) >= NUM_CARRIERS:
                loop.call_soon_threadsafe(end_event.set)

        channel.register_callback(pb.MessageV1.RUN_DATA_END_MESSAGE_FIELD_NUMBER, on_data_end)

        try:
            # Push a config with 8 ADC channels on the first carrier.
            adc_channels = [pb.AdcChannel(idx=i, gain=1.0, offset=0.0) for i in range(requested_channels)]
            carrier_config = pb.Item(
                entity=pb.EntityId(path="/00-00-00-00-00-00"),
                adc_config=pb.AdcConfig(channels=adc_channels),
            )
            module = pb.Module(items=[carrier_config])
            await asyncio.wait_for(channel.set_module(module), timeout=OP_TIMEOUT)

            # Send StartRunCommand with a different DaqConfig channel count (4).
            cmd = _make_run_command(op_time_ns, num_channels=4, sample_rate=1000)
            await asyncio.wait_for(channel.start_run_request(cmd), timeout=OP_TIMEOUT)
            await asyncio.wait_for(end_event.wait(), timeout=RUN_TIMEOUT)

            assert (
                len(end_messages) == NUM_CARRIERS
            ), f"Expected {NUM_CARRIERS} RunDataEndMessages, got {len(end_messages)}"
            # Channel count should come from ConfigCommand (8), not DaqConfig (4).
            for msg in end_messages:
                assert (
                    msg.data.channel_stride == requested_channels
                ), f"Expected channel_stride={requested_channels}, got {msg.data.channel_stride}"
                assert len(msg.data.channels) == requested_channels
        finally:
            await channel.stop()

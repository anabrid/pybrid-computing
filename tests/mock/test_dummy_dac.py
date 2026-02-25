# Copyright (c) 2022-2025 anabrid GmbH
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
Comprehensive integration tests for DummyDAC.

Tests all error injection modes and complete run cycles using the native
C++ ControlChannel (via AsyncControlChannel) over a real TCP connection.
No internal Python Protocol mocking.
"""

import asyncio
import re
import warnings
from uuid import uuid4

import pytest

import pybrid.base.proto.main_pb2 as pb
from pybrid.mock import DummyDAC, DummyDACConfig, DummyDACMacMode, DummyDACErrorStage
from pybrid.redac.control import AsyncControlChannel

try:
    from pybrid.native._impl import ControlChannel as NativeControlChannel
    _NATIVE_AVAILABLE = True
except ImportError:
    _NATIVE_AVAILABLE = False
    NativeControlChannel = None

_native_skipif = pytest.mark.skipif(
    not _NATIVE_AVAILABLE,
    reason="pybrid.native._impl.ControlChannel is not available (C++ bindings not built)",
)

LOCALHOST = "127.0.0.1"
OP_TIMEOUT = 5.0
# Short run op-time for fast tests.
RUN_OP_TIME_NS = 10_000_000  # 10 ms
# Budget for an entire run including state callbacks.
RUN_TIMEOUT = RUN_OP_TIME_NS / 1e9 + 2.0
# Number of carriers in REDAC mode (default).
NUM_CARRIERS = 2
# Longer op-time used for the FEWER_SAMPLES test.
FEWER_SAMPLES_OP_TIME_NS = 1_000_000_000  # 1 second
FEWER_SAMPLES_TIMEOUT = FEWER_SAMPLES_OP_TIME_NS / 1e9 + 2.0


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


def _make_run_command(op_time_ns: int, num_channels: int = 2, sample_rate: int = 100) -> pb.StartRunCommand:
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
        calibration_config=pb.CalibrationConfig(enabled=False),
    )


@_native_skipif
@pytest.mark.asyncio
async def test_fewer_samples_error_injection():
    sample_rate = 1000
    expected_samples_per_carrier = int(sample_rate * (FEWER_SAMPLES_OP_TIME_NS / 1e9))
    expected_total_samples = expected_samples_per_carrier * NUM_CARRIERS

    config = DummyDACConfig(error_stage=DummyDACErrorStage.FEWER_SAMPLES)
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
        channel.register_callback(
            pb.MessageV1.RUN_STATE_CHANGE_MESSAGE_FIELD_NUMBER, on_state_change
        )

        try:
            cmd = _make_run_command(FEWER_SAMPLES_OP_TIME_NS, num_channels=4, sample_rate=sample_rate)
            await asyncio.wait_for(channel.start_run_request(cmd), timeout=OP_TIMEOUT)
            await asyncio.wait_for(done_event.wait(), timeout=FEWER_SAMPLES_TIMEOUT)

            total_samples = sum(msg.data.sample_count for msg in data_messages)
            assert total_samples < expected_total_samples, (
                f"Expected fewer than {expected_total_samples} samples with FEWER_SAMPLES injection, "
                f"got {total_samples}"
            )
        finally:
            await channel.stop()


@_native_skipif
@pytest.mark.asyncio
async def test_drop_takeoff_state():
    config = DummyDACConfig(error_stage=DummyDACErrorStage.DROP_TAKEOFF_STATE)
    async with DummyDAC(LOCALHOST, 0, config) as server:
        port = server.port
        channel = await _make_channel(port)
        loop = asyncio.get_running_loop()

        states: list[int] = []
        done_event = asyncio.Event()

        def on_state_change(msg: pb.MessageV1) -> None:
            new_state = msg.run_state_change_message.new_
            states.append(new_state)
            if new_state == pb.RunState.DONE:
                loop.call_soon_threadsafe(done_event.set)

        channel.register_callback(
            pb.MessageV1.RUN_STATE_CHANGE_MESSAGE_FIELD_NUMBER, on_state_change
        )

        try:
            cmd = _make_run_command(RUN_OP_TIME_NS)
            await asyncio.wait_for(channel.start_run_request(cmd), timeout=OP_TIMEOUT)
            await asyncio.wait_for(done_event.wait(), timeout=RUN_TIMEOUT)

            assert pb.RunState.TAKE_OFF not in states, (
                f"TAKE_OFF should be suppressed by DROP_TAKEOFF_STATE, got states: {states}"
            )
            assert pb.RunState.IC in states, f"IC missing from states: {states}"
            assert pb.RunState.DONE in states, f"DONE missing from states: {states}"
        finally:
            await channel.stop()


@_native_skipif
@pytest.mark.asyncio
async def test_drop_done_state():
    config = DummyDACConfig(error_stage=DummyDACErrorStage.DROP_DONE_STATE)
    async with DummyDAC(LOCALHOST, 0, config) as server:
        port = server.port
        channel = await _make_channel(port)
        loop = asyncio.get_running_loop()

        states: list[int] = []
        op_end_event = asyncio.Event()

        def on_state_change(msg: pb.MessageV1) -> None:
            new_state = msg.run_state_change_message.new_
            states.append(new_state)
            # Since DONE is never sent, wait for OP_END as terminal signal.
            if new_state == pb.RunState.OP_END:
                loop.call_soon_threadsafe(op_end_event.set)

        channel.register_callback(
            pb.MessageV1.RUN_STATE_CHANGE_MESSAGE_FIELD_NUMBER, on_state_change
        )

        try:
            cmd = _make_run_command(RUN_OP_TIME_NS)
            await asyncio.wait_for(channel.start_run_request(cmd), timeout=OP_TIMEOUT)
            await asyncio.wait_for(op_end_event.wait(), timeout=RUN_TIMEOUT)

            assert pb.RunState.DONE not in states, (
                f"DONE should be suppressed by DROP_DONE_STATE, got states: {states}"
            )
            assert pb.RunState.TAKE_OFF in states, f"TAKE_OFF missing from states: {states}"
            assert pb.RunState.OP_END in states, f"OP_END missing from states: {states}"
        finally:
            await channel.stop()


@_native_skipif
@pytest.mark.asyncio
async def test_during_run_error():
    config = DummyDACConfig(error_stage=DummyDACErrorStage.DURING_RUN)
    async with DummyDAC(LOCALHOST, 0, config) as server:
        port = server.port
        channel = await _make_channel(port)
        loop = asyncio.get_running_loop()

        states: list[int] = []
        error_event = asyncio.Event()

        def on_state_change(msg: pb.MessageV1) -> None:
            new_state = msg.run_state_change_message.new_
            states.append(new_state)
            if new_state == pb.RunState.ERROR:
                loop.call_soon_threadsafe(error_event.set)

        channel.register_callback(
            pb.MessageV1.RUN_STATE_CHANGE_MESSAGE_FIELD_NUMBER, on_state_change
        )

        try:
            cmd = _make_run_command(RUN_OP_TIME_NS)
            await asyncio.wait_for(channel.start_run_request(cmd), timeout=OP_TIMEOUT)
            await asyncio.wait_for(error_event.wait(), timeout=RUN_TIMEOUT)

            assert pb.RunState.ERROR in states, f"ERROR state missing: {states}"
            assert pb.RunState.DONE not in states, (
                f"DONE should not appear after DURING_RUN error, got states: {states}"
            )
        finally:
            await channel.stop()


@_native_skipif
@pytest.mark.asyncio
async def test_physical_mac_mode():
    config = DummyDACConfig(mac_mode=DummyDACMacMode.PHYSICAL)
    async with DummyDAC(LOCALHOST, 0, config) as server:
        port = server.port
        channel = await _make_channel(port)
        try:
            entity = await asyncio.wait_for(channel.describe(), timeout=OP_TIMEOUT)
            mac_pattern = re.compile(r'^[0-9A-Fa-f]{2}(-[0-9A-Fa-f]{2}){5}$')
            for carrier in entity.children:
                mac = carrier.id
                assert not mac.startswith("00-00-00-00-00-"), (
                    f"Physical MAC should not start with virtual prefix, got: {mac}"
                )
                assert mac_pattern.match(mac), f"Invalid MAC format: {mac}"
        finally:
            await channel.stop()


@_native_skipif
@pytest.mark.asyncio
async def test_extract_error_injection():
    config = DummyDACConfig(
        error_stage=DummyDACErrorStage.AT_EXTRACT,
        error_message="Simulated extract error",
    )
    async with DummyDAC(LOCALHOST, 0, config) as server:
        port = server.port
        channel = await _make_channel(port)
        try:
            # First store some config.
            test_config = pb.Config(entity=pb.EntityId(path="/00-00-00-00-00-00/0/M0"))
            bundle = pb.ConfigBundle(configs=[test_config])
            await asyncio.wait_for(channel.set_config_bundle(bundle), timeout=OP_TIMEOUT)

            # Now try to extract — should raise RuntimeError due to error injection.
            with pytest.raises(RuntimeError, match="Simulated extract error"):
                await asyncio.wait_for(
                    channel.get_config("/00-00-00-00-00-00", recursive=True),
                    timeout=OP_TIMEOUT,
                )
        finally:
            await channel.stop()


def test_dummy_controller_deprecation_warning():
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        from pybrid.redac.dummy import DummyController
        _ = DummyController()

        assert len(w) >= 1, "Expected at least one warning"
        deprecation_warnings = [
            warning for warning in w if issubclass(warning.category, DeprecationWarning)
        ]
        assert len(deprecation_warnings) >= 1, "Expected at least one DeprecationWarning"
        assert "DummyDAC" in str(deprecation_warnings[0].message), (
            f"Expected 'DummyDAC' in deprecation message, got: {deprecation_warnings[0].message}"
        )


@_native_skipif
@pytest.mark.asyncio
async def test_complete_run_cycle():
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

        states: list[int] = []
        data_messages: list[pb.RunDataMessage] = []
        data_end_count = 0
        done_event = asyncio.Event()

        def on_state_change(msg: pb.MessageV1) -> None:
            new_state = msg.run_state_change_message.new_
            states.append(new_state)
            if new_state == pb.RunState.DONE:
                loop.call_soon_threadsafe(done_event.set)

        def on_data(msg: pb.MessageV1) -> None:
            data_messages.append(msg.run_data_message)

        def on_data_end(msg: pb.MessageV1) -> None:
            nonlocal data_end_count
            data_end_count += 1

        channel.register_callback(
            pb.MessageV1.RUN_STATE_CHANGE_MESSAGE_FIELD_NUMBER, on_state_change
        )
        channel.register_callback(pb.MessageV1.RUN_DATA_MESSAGE_FIELD_NUMBER, on_data)
        channel.register_callback(pb.MessageV1.RUN_DATA_END_MESSAGE_FIELD_NUMBER, on_data_end)

        try:
            cmd = _make_run_command(op_time_ns, num_channels=num_channels, sample_rate=sample_rate)
            await asyncio.wait_for(channel.start_run_request(cmd), timeout=OP_TIMEOUT)
            await asyncio.wait_for(done_event.wait(), timeout=run_timeout)

            # Verify full state machine sequence.
            assert pb.RunState.TAKE_OFF in states, f"TAKE_OFF missing: {states}"
            assert pb.RunState.IC in states, f"IC missing: {states}"
            assert pb.RunState.OP in states, f"OP missing: {states}"
            assert pb.RunState.OP_END in states, f"OP_END missing: {states}"
            assert pb.RunState.DONE in states, f"DONE missing: {states}"

            # Verify minimum expected sample count.
            total_samples = sum(msg.data.sample_count for msg in data_messages)
            assert total_samples >= min_expected_total_samples, (
                f"Expected at least {min_expected_total_samples} samples, got {total_samples}"
            )

            # Verify data-end count matches number of carriers.
            assert data_end_count == NUM_CARRIERS, (
                f"Expected {NUM_CARRIERS} RunDataEndMessages, got {data_end_count}"
            )
        finally:
            await channel.stop()

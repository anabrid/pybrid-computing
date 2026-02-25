# Copyright (c) 2022-2025 anabrid GmbH
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""Tests for DummyDAC simulate_op_time configuration flag.

Verifies that when simulate_op_time=True the DummyDAC introduces a wall-clock
delay during the OP phase proportional to the configured op_time, and that when
simulate_op_time=False (the default) runs complete without artificial delay.
"""

import asyncio
import time
from uuid import uuid4

import pytest

import pybrid.base.proto.main_pb2 as pb
from pybrid.mock import DummyDAC, DummyDACConfig
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
CHANNEL_TIMEOUT = 5.0
# OP time used in tests: 500 ms expressed in nanoseconds.
OP_TIME_NS = 500_000_000  # 500 ms
# Budget for the full test run including scheduling overhead.
TEST_TIMEOUT = 10.0


async def _make_channel(port: int) -> AsyncControlChannel:
    """Create and start an AsyncControlChannel connected to *port* on localhost.

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
        CHANNEL_TIMEOUT,
    )
    channel = AsyncControlChannel(native)
    channel.start()
    return channel


def _make_run_command(op_time_ns: int) -> pb.StartRunCommand:
    """Build a minimal StartRunCommand with the given op_time.

    Args:
        op_time_ns: OP phase duration in nanoseconds.

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
            num_channels=0,
            sample_rate=1000,
            sample_op=False,
        ),
        sync_config=pb.SyncConfig(enabled=False),
        calibration_config=pb.CalibrationConfig(enabled=False),
    )


class TestSimulateOpTime:
    """Tests for DummyDACConfig.simulate_op_time flag."""

    @pytest.mark.asyncio
    async def test_simulate_op_time_delays_run(self):
        """With simulate_op_time=True a 500 ms run takes >= 0.4 s wall-clock time."""
        config = DummyDACConfig(simulate_op_time=True)
        async with DummyDAC(LOCALHOST, 0, config) as server:
            channel = await _make_channel(server.port)
            loop = asyncio.get_running_loop()
            done_event = asyncio.Event()

            def on_state_change(msg: pb.MessageV1) -> None:
                if msg.run_state_change_message.new_ == pb.RunState.DONE:
                    loop.call_soon_threadsafe(done_event.set)

            channel.register_callback(
                pb.MessageV1.RUN_STATE_CHANGE_MESSAGE_FIELD_NUMBER,
                on_state_change,
            )

            try:
                cmd = _make_run_command(OP_TIME_NS)
                t_start = time.monotonic()
                await asyncio.wait_for(
                    channel.start_run_request(cmd), timeout=CHANNEL_TIMEOUT
                )
                await asyncio.wait_for(done_event.wait(), timeout=TEST_TIMEOUT)
                elapsed = time.monotonic() - t_start

                assert elapsed >= 0.4, (
                    f"With simulate_op_time=True and op_time=500ms, expected elapsed >= 0.4s, "
                    f"got {elapsed:.3f}s.  Did you implement asyncio.sleep(op_time_seconds) "
                    f"in StartRunHandler._execute_run?"
                )
            finally:
                await channel.stop()

    @pytest.mark.asyncio
    async def test_simulate_op_time_false_no_delay(self):
        """With simulate_op_time=False (default) a 500 ms run completes in < 0.3 s (regression guard)."""
        config = DummyDACConfig(simulate_op_time=False)
        async with DummyDAC(LOCALHOST, 0, config) as server:
            channel = await _make_channel(server.port)
            loop = asyncio.get_running_loop()
            done_event = asyncio.Event()

            def on_state_change(msg: pb.MessageV1) -> None:
                if msg.run_state_change_message.new_ == pb.RunState.DONE:
                    loop.call_soon_threadsafe(done_event.set)

            channel.register_callback(
                pb.MessageV1.RUN_STATE_CHANGE_MESSAGE_FIELD_NUMBER,
                on_state_change,
            )

            try:
                cmd = _make_run_command(OP_TIME_NS)
                t_start = time.monotonic()
                await asyncio.wait_for(
                    channel.start_run_request(cmd), timeout=CHANNEL_TIMEOUT
                )
                await asyncio.wait_for(done_event.wait(), timeout=TEST_TIMEOUT)
                elapsed = time.monotonic() - t_start

                assert elapsed < 0.3, (
                    f"With simulate_op_time=False, expected elapsed < 0.3s, "
                    f"got {elapsed:.3f}s.  The default DummyDAC mode must not introduce delay."
                )
            finally:
                await channel.stop()

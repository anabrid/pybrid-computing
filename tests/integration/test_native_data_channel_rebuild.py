#  Copyright (c) 2026 anabrid GmbH
#  Contact: https://www.anabrid.com/licensing/
#  SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""Integration test for DataChannel::reconnect."""

import asyncio
from uuid import uuid4

import pytest

import pybrid.base.proto.main_pb2 as pb
from pybrid.mock import DummyDAC, DummyDACConfig, DummyDACMacMode

try:
    from pybrid.native._impl import ControlChannel as _NativeControlChannel
    from pybrid.native import SampleDecodingDataChannel
    _NATIVE_AVAILABLE = True
except ImportError:
    _NATIVE_AVAILABLE = False
    _NativeControlChannel = None
    SampleDecodingDataChannel = None

pytestmark = pytest.mark.skipif(
    not _NATIVE_AVAILABLE,
    reason="pybrid.native._impl is not available (C++ bindings not built)",
)

LOCALHOST = "127.0.0.1"
OP_TIMEOUT = 5.0
RUN_OP_TIME_NS = 50_000_000  # 50 ms
RUN_TIMEOUT = RUN_OP_TIME_NS / 1e9 + 3.0


def _make_run_command(op_time_ns: int) -> pb.StartRunCommand:
    """Build a short StartRunCommand that yields at least a few sample blobs."""
    return pb.StartRunCommand(
        run=pb.Run(id=str(uuid4()), chunk=0),
        run_config=pb.RunConfig(
            ic_time=pb.Time(value=100_000, prefix=pb.Prefix.NANO),
            op_time=pb.Time(value=op_time_ns, prefix=pb.Prefix.NANO),
            halt_on_overload=False,
        ),
        daq_config=pb.DaqConfig(
            num_channels=4,
            sample_rate=1000,
            sample_op=True,
            sample_op_end=True,
        ),
        sync_config=pb.SyncConfig(enabled=False),
    )


def _drain_ibuffer(output_queue) -> int:
    """Return the number of blobs drained from an IBuffer."""
    drained = 0
    buf = bytearray(1024 * 1024)
    while True:
        n = output_queue.get(buf, len(buf))
        if n == 0:
            break
        drained += 1
    return drained


@pytest.mark.asyncio
async def test_data_channel_reconnect_preserves_receive_capability():
    """reconnect() must tear down and restart the receive loop cleanly.

    The call must leave the data channel in a ``running`` state, preserve the
    TCP-fallback status it had before the rebuild, and — critically for the
    proxy firmware flow — remain usable for a subsequent run without the
    caller reinstalling the control channel, callbacks, or the output queue.
    """
    from pybrid.redac.connection import ConnectionManager
    from pybrid.redac.control import AsyncControlChannel

    config = DummyDACConfig(mac_mode=DummyDACMacMode.VIRTUAL)
    async with DummyDAC(LOCALHOST, 0, config) as dac:
        port = dac.port

        cm = ConnectionManager()
        try:
            await cm.add_device(LOCALHOST, port)

            unique_conns = cm.get_unique_connections()
            assert len(unique_conns) == 1, (
                f"Expected 1 DeviceConnection, got {len(unique_conns)}"
            )
            conn = next(iter(unique_conns))
            control: AsyncControlChannel = conn.control
            data_channel = conn.data

            assert data_channel is not None, "No data channel after add_device()"
            assert data_channel.is_running(), (
                "Data channel must be running before reconnect()"
            )

            # reconnect() blocks on control-channel round-trips during
            # UDP re-negotiation, so it must be dispatched off the event loop.
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, data_channel.reconnect)

            assert not data_channel.is_using_tcp_fallback(), (
                "reconnect() should re-establish UDP against the DummyDAC, "
                "not silently fall back to TCP"
            )

            assert data_channel.is_running(), (
                "Data channel must still be running after reconnect()"
            )

            # Exercise a run over the rebuilt data path. A rebuild that leaked
            # the receive thread or left the UDP socket disconnected would
            # manifest here as an empty output queue or a timeout.
            output_queue = conn.output_queue

            done_event = asyncio.Event()

            def _on_state(msg: pb.MessageV1) -> None:
                if msg.run_state_change_message.new_ == pb.RunState.DONE:
                    loop.call_soon_threadsafe(done_event.set)

            control.register_callback(
                pb.MessageV1.RUN_STATE_CHANGE_MESSAGE_FIELD_NUMBER,
                _on_state,
            )
            try:
                cmd = _make_run_command(RUN_OP_TIME_NS)
                await asyncio.wait_for(
                    control.start_run_request(cmd), timeout=OP_TIMEOUT
                )
                await asyncio.wait_for(done_event.wait(), timeout=RUN_TIMEOUT)
                await asyncio.sleep(0.1)

                drained = _drain_ibuffer(output_queue)
                assert drained > 0, (
                    "No sample blobs delivered after reconnect(); "
                    "receive pipeline is broken post-rebuild"
                )
            finally:
                control.unregister_callback(
                    pb.MessageV1.RUN_STATE_CHANGE_MESSAGE_FIELD_NUMBER
                )
        finally:
            await cm.close_all()

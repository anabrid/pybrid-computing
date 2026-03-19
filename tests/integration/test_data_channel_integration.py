# Copyright (c) 2022-2025 anabrid GmbH
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""Integration tests for SampleDecodingDataChannel wired into ConnectionManager.

These tests verify:
- ConnectionManager._create_connections() creates and starts a SampleDecodingDataChannel
- The data channel is accessible via DeviceConnection.data
- Samples produced by DummyDAC during a run are captured in the IBuffer output queue
- TCP fallback is used when UDP streaming is refused (DummyDAC default behaviour)
- LockFreeBuffer is importable from pybrid.native and usable from Python

All tests require the native C++ extension (_impl). They are skipped if the
extension has not been built.
"""

import asyncio
import struct
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

# Short run op-time (50 ms) gives enough time for at least a few data packets
# to arrive while keeping the tests fast.
RUN_OP_TIME_NS = 50_000_000  # 50 ms
RUN_TIMEOUT = RUN_OP_TIME_NS / 1e9 + 3.0  # op-time + 3 s headroom


def _make_run_command(
    op_time_ns: int,
    num_channels: int = 4,
    sample_rate: int = 1000,
) -> pb.StartRunCommand:
    """Build a standard StartRunCommand for integration testing.

    Args:
        op_time_ns:   OP phase duration in nanoseconds.
        num_channels: Number of DAQ channels to sample.
        sample_rate:  DAQ sample rate in samples per second.

    Returns:
        A populated :class:`pb.StartRunCommand` ready to send.
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


def _drain_ibuffer(output_queue) -> list[bytes]:
    """Drain all blobs from an IBuffer and return them as a list of bytes.

    Reads up to 1 MB per blob; stops when get() returns 0 (queue empty).

    Args:
        output_queue: An IBuffer instance (e.g. LockFreeBuffer).

    Returns:
        List of raw blob byte strings, one entry per decoded sample blob.
    """
    blobs: list[bytes] = []
    buf = bytearray(1024 * 1024)  # 1 MB scratch space
    while True:
        n = output_queue.get(buf, len(buf))
        if n == 0:
            break
        blobs.append(bytes(buf[:n]))
    return blobs


@pytest.mark.asyncio
async def test_data_channel_created_on_add_device():
    """add_device() creates and starts a SampleDecodingDataChannel on the DeviceConnection."""
    from pybrid.redac.connection import ConnectionManager

    config = DummyDACConfig(mac_mode=DummyDACMacMode.VIRTUAL)
    async with DummyDAC(LOCALHOST, 0, config) as dac:
        port = dac.port

        cm = ConnectionManager()
        try:
            carriers, new_connections = await cm.add_device(LOCALHOST, port)

            assert new_connections, "add_device() returned no connections"

            unique_conns = cm.get_unique_connections()
            assert len(unique_conns) == 1, (
                f"Expected 1 unique DeviceConnection, got {len(unique_conns)}"
            )
            conn = next(iter(unique_conns))

            assert conn.data is not None, (
                "DeviceConnection.data is None after add_device(); "
                "expected a SampleDecodingDataChannel"
            )
            assert conn.data.is_running(), (
                "SampleDecodingDataChannel.is_running() is False after add_device(); "
                "expected it to be started automatically"
            )
        finally:
            await cm.close_all()


@pytest.mark.asyncio
async def test_data_channel_receives_samples_via_run():
    """After a run completes, the IBuffer output queue contains at least one non-trivial blob."""
    from pybrid.redac.connection import ConnectionManager
    from pybrid.redac.control import AsyncControlChannel

    config = DummyDACConfig(mac_mode=DummyDACMacMode.VIRTUAL)
    async with DummyDAC(LOCALHOST, 0, config) as dac:
        port = dac.port

        cm = ConnectionManager()
        try:
            await cm.add_device(LOCALHOST, port)

            unique_conns = cm.get_unique_connections()
            conn = next(iter(unique_conns))
            control: AsyncControlChannel = conn.control
            data_channel = conn.data

            assert data_channel is not None, "No data channel after add_device()"
            assert data_channel.is_running(), "Data channel not running before run"
            output_queue = conn.output_queue

            # Wait for DONE via a state-change callback on the control channel.
            loop = asyncio.get_running_loop()
            done_event = asyncio.Event()

            def _on_state(msg: pb.MessageV1) -> None:
                if msg.run_state_change_message.new_ == pb.RunState.DONE:
                    loop.call_soon_threadsafe(done_event.set)

            control.register_callback(
                pb.MessageV1.RUN_STATE_CHANGE_MESSAGE_FIELD_NUMBER,
                _on_state,
            )

            cmd = _make_run_command(
                op_time_ns=RUN_OP_TIME_NS,
                num_channels=4,
                sample_rate=1000,
            )
            await asyncio.wait_for(control.start_run_request(cmd), timeout=OP_TIMEOUT)
            await asyncio.wait_for(done_event.wait(), timeout=RUN_TIMEOUT)

            # Allow a brief window for in-flight data to land in the queue.
            await asyncio.sleep(0.1)

            assert output_queue.len() > 0, (
                "IBuffer output queue is empty after run completed; "
                "expected at least one decoded sample blob"
            )

            # Drain and verify blobs are non-trivially sized.
            blobs = _drain_ibuffer(output_queue)
            assert len(blobs) > 0, "Drained zero blobs from output_queue"

            # Each blob must be at least 16 bytes (DecodedSampleBlobHeader size).
            HEADER_SIZE = 16
            for i, blob in enumerate(blobs):
                assert len(blob) >= HEADER_SIZE, (
                    f"Blob {i} is only {len(blob)} bytes, expected >= {HEADER_SIZE} "
                    "(minimum DecodedSampleBlobHeader size)"
                )

            control.unregister_callback(
                pb.MessageV1.RUN_STATE_CHANGE_MESSAGE_FIELD_NUMBER
            )
        finally:
            await cm.close_all()


@pytest.mark.asyncio
async def test_data_channel_tcp_fallback_with_dummydac():
    """Explicit UDP refusal triggers TCP fallback; data still arrives in the IBuffer."""
    from pybrid.redac.connection import ConnectionManager
    from pybrid.redac.control import AsyncControlChannel

    config = DummyDACConfig(mac_mode=DummyDACMacMode.VIRTUAL, accept_udp_streaming=False)
    async with DummyDAC(LOCALHOST, 0, config) as dac:
        port = dac.port

        cm = ConnectionManager()
        try:
            await cm.add_device(LOCALHOST, port)

            unique_conns = cm.get_unique_connections()
            conn = next(iter(unique_conns))
            data_channel = conn.data
            control: AsyncControlChannel = conn.control

            assert data_channel is not None, "No data channel after add_device()"

            # DummyDAC always refuses UDP → TCP fallback must be active.
            assert data_channel.is_using_tcp_fallback(), (
                "Expected is_using_tcp_fallback() == True because DummyDAC refuses "
                "UDP streaming, but TCP fallback is not active"
            )
            assert data_channel.is_running(), (
                "Data channel not running after TCP fallback was established"
            )

            # Even in TCP fallback mode, data must flow during a run.
            loop = asyncio.get_running_loop()
            done_event = asyncio.Event()

            def _on_state(msg: pb.MessageV1) -> None:
                if msg.run_state_change_message.new_ == pb.RunState.DONE:
                    loop.call_soon_threadsafe(done_event.set)

            control.register_callback(
                pb.MessageV1.RUN_STATE_CHANGE_MESSAGE_FIELD_NUMBER,
                _on_state,
            )

            cmd = _make_run_command(
                op_time_ns=RUN_OP_TIME_NS,
                num_channels=4,
                sample_rate=1000,
            )
            await asyncio.wait_for(control.start_run_request(cmd), timeout=OP_TIMEOUT)
            await asyncio.wait_for(done_event.wait(), timeout=RUN_TIMEOUT)
            await asyncio.sleep(0.1)

            output_queue = conn.output_queue
            assert output_queue.len() > 0, (
                "IBuffer output queue is empty after run via TCP fallback; "
                "expected sample blobs even when UDP is unavailable"
            )

            control.unregister_callback(
                pb.MessageV1.RUN_STATE_CHANGE_MESSAGE_FIELD_NUMBER
            )
        finally:
            await cm.close_all()


def test_ibuffer_python_bindings():
    """LockFreeBuffer put/get roundtrip preserves exact bytes and len() tracks item count correctly."""
    from pybrid.native import LockFreeBuffer

    buf = LockFreeBuffer()

    # Initially empty.
    assert buf.len() == 0, f"Expected empty buffer, got len={buf.len()}"

    # Put two distinct items.
    item_a = b"hello_data_blob_\x00\x01\x02\x03"
    item_b = b"\xff\xfe" * 64  # 128-byte binary blob

    buf.put(item_a)
    assert buf.len() == 1, f"Expected 1 item after first put, got {buf.len()}"

    buf.put(item_b)
    assert buf.len() == 2, f"Expected 2 items after second put, got {buf.len()}"

    # Retrieve first item and verify exact bytes are preserved.
    scratch = bytearray(len(item_a) + 64)
    n = buf.get(scratch, len(scratch))
    assert n == len(item_a), (
        f"get() returned {n} bytes, expected {len(item_a)}"
    )
    assert bytes(scratch[:n]) == item_a, (
        "Retrieved bytes do not match original item_a"
    )

    # One item left.
    assert buf.len() == 1, f"Expected 1 item remaining, got {buf.len()}"

    # Retrieve second item.
    scratch2 = bytearray(len(item_b) + 64)
    n2 = buf.get(scratch2, len(scratch2))
    assert n2 == len(item_b), (
        f"get() returned {n2} bytes for item_b, expected {len(item_b)}"
    )
    assert bytes(scratch2[:n2]) == item_b, (
        "Retrieved bytes do not match original item_b"
    )

    # Buffer should be empty now.
    assert buf.len() == 0, f"Expected empty buffer after drain, got {buf.len()}"

    # get() on empty buffer returns 0 without raising.
    dummy = bytearray(64)
    n_empty = buf.get(dummy, len(dummy))
    assert n_empty == 0, f"get() on empty buffer returned {n_empty}, expected 0"

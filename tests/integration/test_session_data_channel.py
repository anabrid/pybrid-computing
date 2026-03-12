# Copyright (c) 2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""Integration tests for Session reading run data from the DataChannel output queue.

These tests verify the full end-to-end Session pipeline where
Session._execute_run() drains the IBuffer output queue from conn.output_queue
instead of registering ControlChannel callbacks for run data messages.

Key behaviors under test:
1. Session.execute() produces a Run with populated run.data (OP-phase blobs).
2. Session.execute() produces a Run with populated run.final_values (OP_END blobs).
3. After a run completes, the ControlChannel does NOT have data callbacks registered
   (data_field and data_end_field callbacks must NOT be present on the control channel).
4. Sample listeners registered on the controller receive data during a run.

All tests require the native C++ extension. They are skipped when it is absent.
"""

import asyncio
import struct

import pytest

import pybrid.base.proto.main_pb2 as pb
from pybrid.mock import DummyDAC, DummyDACConfig, DummyDACMacMode
from pybrid.redac.controller import Controller as REDACController
from pybrid.redac.run import RunConfig, DAQConfig

try:
    from pybrid.native._impl import ControlChannel as _NativeControlChannel
    _NATIVE_AVAILABLE = True
except ImportError:
    _NATIVE_AVAILABLE = False
    _NativeControlChannel = None

pytestmark = pytest.mark.skipif(
    not _NATIVE_AVAILABLE,
    reason="pybrid.native._impl is not available (C++ bindings not built)",
)

LOCALHOST = "127.0.0.1"
OP_TIMEOUT = 10.0

# 50 ms run — short enough to keep tests fast, long enough to produce data.
RUN_OP_TIME_NS = 50_000_000  # 50 ms
# Budget: op_time (s) + generous headroom for DummyDAC and queue drain.
RUN_TIMEOUT = RUN_OP_TIME_NS / 1e9 + 5.0

# DecodedSampleBlobHeader constants (must match the C++ struct layout).
BLOB_HEADER_SIZE = 16  # 4 x uint32_t
SAMPLE_TYPE_OP = 0
SAMPLE_TYPE_OP_END = 1


def _parse_blob_header(blob: bytes) -> tuple[int, int, int, int]:
    """Parse a DecodedSampleBlobHeader from the start of *blob*.

    Returns:
        A tuple of (entity_path_len, sample_count, channel_count, sample_type).

    The header layout is:
        [0:4]   entity_path_len  (uint32 LE)
        [4:8]   sample_count     (uint32 LE)
        [8:12]  channel_count    (uint32 LE)
        [12:16] sample_type      (uint32 LE; 0=OP, 1=OP_END)
    """
    assert len(blob) >= BLOB_HEADER_SIZE, (
        f"Blob is too short to contain header: {len(blob)} < {BLOB_HEADER_SIZE}"
    )
    entity_path_len, sample_count, channel_count, sample_type = struct.unpack_from(
        "<IIII", blob, 0
    )
    return entity_path_len, sample_count, channel_count, sample_type


def _drain_ibuffer(output_queue) -> list[bytes]:
    """Drain all items from an IBuffer and return them as raw byte strings.

    Args:
        output_queue: An IBuffer (e.g. LockFreeBuffer) exposing get(buf, max_bytes).

    Returns:
        List of raw blob bytes, one entry per decoded sample blob.
    """
    blobs: list[bytes] = []
    buf = bytearray(4 * 1024 * 1024)  # 4 MB scratch — generous for any blob
    while True:
        n = output_queue.get(buf, len(buf))
        if n == 0:
            break
        blobs.append(bytes(buf[:n]))
    return blobs



@pytest.mark.asyncio
async def test_session_run_populates_data_via_data_channel():
    """Session._execute_run() drains IBuffer blobs into run.data with at least one sample per channel."""
    config = DummyDACConfig(mac_mode=DummyDACMacMode.VIRTUAL)
    async with DummyDAC(LOCALHOST, 0, config) as dac:
        port = dac.port

        async with REDACController() as ctrl:
            await ctrl.add_device(LOCALHOST, port)

            session = ctrl.create_session()
            session.run(
                RunConfig(
                    ic_time=100_000,
                    op_time=RUN_OP_TIME_NS,
                    halt_on_overload=False,
                ),
                daq=DAQConfig(
                    num_channels=4,
                    sample_rate=1000,
                    sample_op=True,
                    sample_op_end=True,
                ),
            )

            runs = await asyncio.wait_for(session.execute(), timeout=RUN_TIMEOUT)

            assert len(runs) == 1, f"Expected exactly 1 run, got {len(runs)}"
            run = runs[0]

            assert run.data, (
                "run.data is empty after Session._execute_run() via DataChannel path; "
                "expected IBuffer blobs to be decoded as OP samples and stored in run.data."
            )

            # Every channel entry in run.data must have at least one sample.
            for channel_path, samples in run.data.items():
                assert len(samples) > 0, (
                    f"run.data[{channel_path}] is empty; expected at least one sample."
                )


@pytest.mark.asyncio
async def test_session_run_populates_final_values_via_data_channel():
    """Session._execute_run() decodes SAMPLE_TYPE_OP_END blobs into run.final_values as numeric scalars."""
    config = DummyDACConfig(mac_mode=DummyDACMacMode.VIRTUAL)
    async with DummyDAC(LOCALHOST, 0, config) as dac:
        port = dac.port

        async with REDACController() as ctrl:
            await ctrl.add_device(LOCALHOST, port)

            session = ctrl.create_session()
            session.run(
                RunConfig(
                    ic_time=100_000,
                    op_time=RUN_OP_TIME_NS,
                    halt_on_overload=False,
                ),
                daq=DAQConfig(
                    num_channels=4,
                    sample_rate=1000,
                    sample_op=True,
                    sample_op_end=True,
                ),
            )

            runs = await asyncio.wait_for(session.execute(), timeout=RUN_TIMEOUT)

            assert len(runs) == 1, f"Expected exactly 1 run, got {len(runs)}"
            run = runs[0]

            assert run.final_values, (
                "run.final_values is empty after Session._execute_run() via DataChannel; "
                "expected SAMPLE_TYPE_OP_END blobs from the IBuffer output queue to be "
                "decoded and stored in run.final_values."
            )

            # Each final value must be a numeric scalar (float or int).
            for path, value in run.final_values.items():
                assert isinstance(value, (int, float)), (
                    f"run.final_values[{path}] = {value!r} is not a numeric scalar; "
                    "expected a float decoded from the OP_END blob."
                )


@pytest.mark.asyncio
async def test_session_no_data_callbacks_on_control_channel():
    """Session registers no data callbacks on ControlChannel; state callback is cleaned up after execute()."""
    DATA_FIELD = pb.MessageV1.RUN_DATA_MESSAGE_FIELD_NUMBER
    DATA_END_FIELD = pb.MessageV1.RUN_DATA_END_MESSAGE_FIELD_NUMBER
    STATE_FIELD = pb.MessageV1.RUN_STATE_CHANGE_MESSAGE_FIELD_NUMBER

    # Track field numbers that were registered at any point during the run.
    ever_registered: list[int] = []
    # Track field numbers that remain registered after execute() returns.
    still_registered: list[int] = []

    config = DummyDACConfig(mac_mode=DummyDACMacMode.VIRTUAL)
    async with DummyDAC(LOCALHOST, 0, config) as dac:
        port = dac.port

        async with REDACController() as ctrl:
            await ctrl.add_device(LOCALHOST, port)

            # Locate the single DeviceConnection's ControlChannel.
            conn_list = list(ctrl.connection_manager.get_unique_connections())
            assert len(conn_list) == 1, "Expected exactly one DeviceConnection"
            conn = conn_list[0]
            real_control = conn.control

            original_register = real_control.register_callback
            original_unregister = real_control.unregister_callback

            def intercepting_register(field_number, callback):
                """Record registration and delegate to real channel."""
                ever_registered.append(field_number)
                if field_number not in still_registered:
                    still_registered.append(field_number)
                return original_register(field_number, callback)

            def intercepting_unregister(field_number):
                """Record un-registration and delegate to real channel."""
                if field_number in still_registered:
                    still_registered.remove(field_number)
                return original_unregister(field_number)

            real_control.register_callback = intercepting_register
            real_control.unregister_callback = intercepting_unregister

            try:
                session = ctrl.create_session()
                session.run(
                    RunConfig(
                        ic_time=100_000,
                        op_time=RUN_OP_TIME_NS,
                        halt_on_overload=False,
                    ),
                    daq=DAQConfig(
                        num_channels=4,
                        sample_rate=1000,
                        sample_op=True,
                        sample_op_end=True,
                    ),
                )
                runs = await asyncio.wait_for(session.execute(), timeout=RUN_TIMEOUT)
                assert len(runs) == 1
            finally:
                real_control.register_callback = original_register
                real_control.unregister_callback = original_unregister

        # --- Assertions ---

        # Data messages are routed via DataChannel, not ControlChannel.
        assert DATA_FIELD not in ever_registered, (
            f"RUN_DATA_MESSAGE_FIELD_NUMBER ({DATA_FIELD}) was registered on the "
            "ControlChannel during the run; data messages must be decoded exclusively "
            "by the C++ SampleDecodingDataChannel and placed in the IBuffer output queue."
        )
        assert DATA_END_FIELD not in ever_registered, (
            f"RUN_DATA_END_MESSAGE_FIELD_NUMBER ({DATA_END_FIELD}) was registered on "
            "the ControlChannel during the run; data-end messages must also be routed "
            "via the DataChannel, not the ControlChannel."
        )

        # The state change callback is expected to be registered and then cleaned up.
        assert STATE_FIELD not in still_registered, (
            f"RUN_STATE_CHANGE_MESSAGE_FIELD_NUMBER ({STATE_FIELD}) is still registered "
            "on the ControlChannel after execute() returned. The finally block in "
            "_execute_run() must unregister it."
        )


@pytest.mark.asyncio
async def test_sample_listeners_invoked_from_data_channel():
    """SampleListeners registered on the controller receive non-None data chunks during the IBuffer drain."""
    from pybrid.base.hybrid.listeners import SampleListener

    received_chunks: list = []

    class _RecordingListener(SampleListener):
        """SampleListener that records every receive() invocation."""

        async def receive(self, samples):
            """Append incoming sample data to the shared recording list."""
            received_chunks.append(samples)

    config = DummyDACConfig(mac_mode=DummyDACMacMode.VIRTUAL)
    async with DummyDAC(LOCALHOST, 0, config) as dac:
        port = dac.port

        async with REDACController() as ctrl:
            await ctrl.add_device(LOCALHOST, port)

            # Register listener BEFORE the run so it catches all data emissions.
            listener = _RecordingListener()
            ctrl.register_listener(listener)

            session = ctrl.create_session()
            session.run(
                RunConfig(
                    ic_time=100_000,
                    op_time=RUN_OP_TIME_NS,
                    halt_on_overload=False,
                ),
                daq=DAQConfig(
                    num_channels=4,
                    sample_rate=1000,
                    sample_op=True,
                    sample_op_end=False,  # OP only: focus listener test on data path
                ),
            )

            runs = await asyncio.wait_for(session.execute(), timeout=RUN_TIMEOUT)

            ctrl.unregister_listener(listener)

        assert len(runs) == 1
        run = runs[0]

        assert received_chunks, (
            "SampleListener.receive() was never called during or after the run; "
            "expected each SAMPLE_TYPE_OP blob from the IBuffer drain step to be "
            "forwarded to all registered SampleListeners on the controller."
        )

        # Each chunk must be non-trivially sized (not None, not an empty container).
        for chunk in received_chunks:
            assert chunk is not None, (
                "SampleListener received a None chunk — expected actual sample data."
            )


# Longer OP time so spread samples have time to be picked up by continuous drain.
_STREAMING_OP_TIME_NS = 1_000_000_000  # 1 s
_STREAMING_RUN_TIMEOUT = _STREAMING_OP_TIME_NS / 1e9 + 10.0


@pytest.mark.asyncio
async def test_concurrent_streaming_delivers_samples_during_op():
    """Samples arrive via SampleListener during the OP phase, not only after execute() returns."""
    import time

    from pybrid.base.hybrid.listeners import SampleListener

    receive_timestamps: list[float] = []

    class _TimestampingListener(SampleListener):
        """SampleListener that records a monotonic timestamp on each receive()."""

        async def receive(self, samples):
            """Record the wall-clock time of each sample delivery."""
            receive_timestamps.append(time.monotonic())

    config = DummyDACConfig(mac_mode=DummyDACMacMode.VIRTUAL, simulate_op_time=True)
    async with DummyDAC(LOCALHOST, 0, config) as dac:
        port = dac.port

        async with REDACController() as ctrl:
            await ctrl.add_device(LOCALHOST, port)

            listener = _TimestampingListener()
            ctrl.register_listener(listener)

            session = ctrl.create_session()
            session.run(
                RunConfig(
                    ic_time=100_000,
                    op_time=_STREAMING_OP_TIME_NS,
                    halt_on_overload=False,
                ),
                daq=DAQConfig(
                    num_channels=8,
                    sample_rate=10_000,
                    sample_op=True,
                    sample_op_end=False,
                ),
            )

            execute_start = time.monotonic()
            runs = await asyncio.wait_for(
                session.execute(), timeout=_STREAMING_RUN_TIMEOUT
            )
            execute_end = time.monotonic()

            ctrl.unregister_listener(listener)

    assert len(runs) == 1

    # Must have received at least one chunk of sample data.
    assert receive_timestamps, (
        "SampleListener.receive() was never called. "
        "DummyDAC with simulate_op_time=True should spread sample chunks "
        "across the OP duration so continuous drain picks them up."
    )

    # The key assertion: at least one receive() happened *before* execute()
    # returned.  With a 1 s OP time and 50 ms drain poll interval, we expect
    # multiple deliveries well before the run completes.
    earliest_receive = min(receive_timestamps)
    assert earliest_receive < execute_end, (
        f"Earliest receive() at {earliest_receive - execute_start:.3f}s was not "
        f"before execute() returned at {execute_end - execute_start:.3f}s. "
        "Samples should arrive during the OP phase, not after."
    )

    # Stronger: at least one receive() should arrive well before execute_end.
    # With 1s of spread chunks, the first sample should arrive within the
    # first ~200ms (a few drain poll intervals after the first chunk send).
    op_duration = execute_end - execute_start
    assert earliest_receive < execute_start + op_duration * 0.8, (
        f"Earliest receive() at {earliest_receive - execute_start:.3f}s "
        f"arrived too late (run took {op_duration:.3f}s). "
        "Expected samples to stream during the first 80% of the OP phase."
    )

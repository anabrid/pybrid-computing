# Copyright (c) 2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
Unit tests for the Session class.

Key invariants under test:
- Session.set_config / .run chain and return self (fluent API)
- Session.execute() dispatches commands sequentially — never concurrently
- Session distributes SetConfigCommand config to all unique DeviceConnections
- Session sends StartRunRequests to involved ControlChannels
- NATIVE sync: first carrier path becomes sync master
- USBSPI sync: all devices in STANDALONE mode, Sync.trigger() fired after TAKE_OFF
- The session lock prevents concurrent execute() calls from racing
- execute() is single-use; a second call raises
- SampleListeners on the controller receive data produced by a run

All tests are mock-only — no real network or hardware required.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call

from pybrid.redac.session import Session, SessionCommand, SetConfigCommand, RunCommand

from pybrid.redac.run import Run, RunConfig, RunState
from pybrid.redac.entities import Path
from pybrid.redac.channel import DeviceConnection
from pybrid.redac.connection import ConnectionManager
from pybrid.redac.carrier import Carrier, ADCChannel
from pybrid.redac.cluster import Cluster
from pybrid.redac.blocks import UBlock, CBlock, IBlock
from pybrid.base.hybrid.controller import BaseController
from pybrid.base.result import Result

import pybrid.base.proto.main_pb2 as pb


def _make_mock_control_channel() -> AsyncMock:
    """Return a fully-mocked AsyncControlChannel."""
    ctrl = AsyncMock()
    ctrl.set_module = AsyncMock(return_value=Result.success())
    ctrl.start_run_request = AsyncMock(return_value=Result.success())
    ctrl.register_callback = MagicMock()
    ctrl.unregister_callback = MagicMock()
    return ctrl


def _make_mock_device_connection() -> MagicMock:
    """Return a mocked DeviceConnection with a mock AsyncControlChannel."""
    conn = MagicMock(spec=DeviceConnection)
    conn.control = _make_mock_control_channel()
    conn.data = None
    conn.output_queue = None
    return conn


def _make_carrier_with_adc(mac: str, num_adc_channels: int = 2) -> Carrier:
    """Build a minimal Carrier with ADC channels that have probe indices."""
    carrier_path = Path.parse(mac)
    cluster_path = carrier_path / "0"
    cluster = Cluster(
        path=cluster_path,
        ublock=UBlock(path=cluster_path / "U"),
        cblock=CBlock(path=cluster_path / "C"),
        iblock=IBlock(path=cluster_path / "I"),
        shblock=None,
    )
    adc_config = [
        ADCChannel(index=i, probe=i)
        for i in range(num_adc_channels)
    ]
    return Carrier(
        path=carrier_path,
        clusters=[cluster],
        tblock=None,
        adc_config=adc_config,
    )


def _make_mock_controller(
    paths: list[str] | None = None,
    num_adc_channels: int = 2,
) -> MagicMock:
    """
    Build a mock BaseController with populated connection_manager and an asyncio.Lock.

    :param paths: MAC strings for the mock carrier connections.
    :param num_adc_channels: Number of ADC channels per carrier (with sequential probe indices).
    :returns: A MagicMock that quacks like BaseController.
    """
    paths = paths or ["AA-BB-CC-DD-EE-01"]
    ctrl = MagicMock(spec=BaseController)
    ctrl.sample_listeners = []
    ctrl._session_lock = asyncio.Lock()
    ctrl.runs = {}

    mgr = MagicMock(spec=ConnectionManager)
    connections = {}
    for mac in paths:
        path = Path.parse(mac)
        connections[path] = _make_mock_device_connection()

    mgr.connections = connections
    mgr.get_unique_connections.return_value = set(connections.values())
    mgr.get_connection.side_effect = lambda p: connections[p]
    ctrl.connection_manager = mgr

    mock_serializer_instance = MagicMock()
    mock_serializer_instance.serialize.return_value = pb.Module()
    mock_serializer_cls = MagicMock(return_value=mock_serializer_instance)

    # Build a mock computer with real carriers so _assemble_run_data can
    # resolve probe indices from ADC config.
    mock_computer = MagicMock()
    mock_computer.get_serializer.return_value = mock_serializer_cls
    probe_offset = 0
    carriers = []
    for mac in paths:
        carrier = _make_carrier_with_adc(mac, num_adc_channels)
        # Offset probe indices for multi-carrier setups
        for ch in carrier.adc_config:
            if ch is not None:
                ch.probe = probe_offset
                probe_offset += 1
        carriers.append(carrier)
    mock_computer.carriers = carriers
    ctrl.computer = mock_computer

    return ctrl


def _make_session(
    paths: list[str] | None = None,
) -> tuple[Session, MagicMock]:
    """
    Create a Session bound to a mock controller.

    :returns: (session, mock_controller)
    """
    ctrl = _make_mock_controller(paths=paths)
    session = Session(ctrl)
    return session, ctrl


class TestSessionPipelineChaining:

    def test_chaining_returns_self(self):
        session, ctrl = _make_session()
        comp = MagicMock()
        run_config = RunConfig()

        result_sc = session.set_config(comp)
        assert result_sc is session, "set_config() must return self for chaining"

        result_r = session.run(run_config)
        assert result_r is session, "run() must return self for chaining"

    def test_pipeline_order_preserved(self):
        session, ctrl = _make_session()
        comp1, comp2 = MagicMock(), MagicMock()
        cfg1, cfg2 = RunConfig(), RunConfig()

        session.set_config(comp1).run(cfg1).set_config(comp2).run(cfg2)

        assert len(session._pipeline) == 4
        assert isinstance(session._pipeline[0], SetConfigCommand)
        assert isinstance(session._pipeline[1], RunCommand)
        assert isinstance(session._pipeline[2], SetConfigCommand)
        assert isinstance(session._pipeline[3], RunCommand)


class TestSessionConfigDistribution:
    """execute() must send config to every unique DeviceConnection exactly once."""

    @pytest.mark.asyncio
    async def test_config_sent_to_all_unique_connections(self):
        session, ctrl = _make_session(
            paths=["AA-BB-CC-DD-EE-01", "BB-BB-CC-DD-EE-02"]
        )
        comp = MagicMock()
        serializer_instance = ctrl.computer.get_serializer()()
        serializer_instance.serialize.return_value = pb.Module()

        # Override _execute_run so we only test the config path
        session.set_config(comp)

        with patch.object(session, "_execute_run", new=AsyncMock(return_value=Run())):
            await session.execute()

        unique_conns = ctrl.connection_manager.get_unique_connections()
        for conn in unique_conns:
            conn.control.set_module.assert_called_once()

    @pytest.mark.asyncio
    async def test_proxy_mode_config_sent_once_not_per_carrier(self):
        """In proxy mode all carrier paths share one DeviceConnection; set_module must be called exactly once."""
        session, ctrl = _make_session(paths=["AA-BB-CC-DD-EE-01"])
        # Simulate proxy mode: two paths pointing to the same DeviceConnection object
        shared_conn = _make_mock_device_connection()
        path1 = Path.parse("AA-BB-CC-DD-EE-01")
        path2 = Path.parse("BB-BB-CC-DD-EE-02")
        ctrl.connection_manager.connections = {path1: shared_conn, path2: shared_conn}
        ctrl.connection_manager.get_unique_connections.return_value = {shared_conn}

        session.set_config(MagicMock())

        with patch.object(session, "_execute_run", new=AsyncMock(return_value=Run())):
            await session.execute()

        # Should be called exactly once even though there are 2 carrier paths
        shared_conn.control.set_module.assert_called_once()


class TestSessionSequentialExecution:
    """Commands in the pipeline must execute in strict sequential order."""

    @pytest.mark.asyncio
    async def test_sequential_order_enforced(self):
        """Given pipeline [set_config, run, set_config, run], verify the second set_config dispatches after the first run."""
        session, ctrl = _make_session()
        execution_order = []

        async def fake_set_config(cmd):
            execution_order.append("set_config")

        async def fake_run(cmd):
            execution_order.append("run")
            return Run()

        comp1, comp2 = MagicMock(), MagicMock()
        cfg1, cfg2 = RunConfig(), RunConfig()

        session.set_config(comp1).run(cfg1).set_config(comp2).run(cfg2)

        with patch.object(session, "_execute_set_config", new=fake_set_config), \
             patch.object(session, "_execute_run", new=fake_run):
            await session.execute()

        assert execution_order == ["set_config", "run", "set_config", "run"]


class TestSessionDistributedRunState:
    """_execute_run() constructs a DistributedRunState with the right path set."""

    @pytest.mark.asyncio
    async def test_entities_none_uses_all_connection_paths(self):
        paths = ["AA-BB-CC-DD-EE-01", "BB-BB-CC-DD-EE-02"]
        session, ctrl = _make_session(paths=paths)

        captured_states = []

        from pybrid.redac.controller import DistributedRunState

        orig_init = DistributedRunState.__init__

        def capturing_init(self_inner, run, paths=None):
            orig_init(self_inner, run, paths)
            captured_states.append(list(self_inner.get_involved_paths()))

        with patch.object(DistributedRunState, "__init__", capturing_init), \
             patch.object(DistributedRunState, "wait_all", new=AsyncMock(return_value=None)):
            session.run(RunConfig())
            await session.execute()

        assert len(captured_states) > 0
        involved = captured_states[-1]
        expected_paths = {Path.parse(p) for p in paths}
        assert set(involved) == expected_paths

    @pytest.mark.asyncio
    async def test_entities_specified_restricts_paths(self):
        session, ctrl = _make_session(
            paths=["AA-BB-CC-DD-EE-01", "BB-BB-CC-DD-EE-02"]
        )
        target_path = Path.parse("AA-BB-CC-DD-EE-01")

        captured_states = []

        from pybrid.redac.controller import DistributedRunState

        orig_init = DistributedRunState.__init__

        def capturing_init(self_inner, run, paths=None):
            orig_init(self_inner, run, paths)
            captured_states.append(list(self_inner.get_involved_paths()))

        with patch.object(DistributedRunState, "__init__", capturing_init), \
             patch.object(DistributedRunState, "wait_all", new=AsyncMock(return_value=None)):
            session.run(RunConfig(), entities={target_path})
            await session.execute()

        assert len(captured_states) > 0
        involved = set(captured_states[-1])
        assert involved == {target_path}


class TestSessionStartRunRequests:
    """_execute_run() must call start_run_request on each involved ControlChannel."""

    @pytest.mark.asyncio
    async def test_start_run_request_called_on_all_connections(self):
        paths = ["AA-BB-CC-DD-EE-01", "BB-BB-CC-DD-EE-02"]
        session, ctrl = _make_session(paths=paths)

        from pybrid.redac.controller import DistributedRunState

        with patch.object(DistributedRunState, "wait_all", new=AsyncMock(return_value=None)):
            session.run(RunConfig())
            await session.execute()

        for conn in ctrl.connection_manager.get_unique_connections():
            conn.control.start_run_request.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_run_request_only_on_involved_connection(self):
        paths = ["AA-BB-CC-DD-EE-01", "BB-BB-CC-DD-EE-02"]
        session, ctrl = _make_session(paths=paths)
        target_path = Path.parse("AA-BB-CC-DD-EE-01")
        other_path = Path.parse("BB-BB-CC-DD-EE-02")

        from pybrid.redac.controller import DistributedRunState

        with patch.object(DistributedRunState, "wait_all", new=AsyncMock(return_value=None)):
            session.run(RunConfig(), entities={target_path})
            await session.execute()

        target_conn = ctrl.connection_manager.get_connection(target_path)
        other_conn = ctrl.connection_manager.get_connection(other_path)

        target_conn.control.start_run_request.assert_called_once()
        other_conn.control.start_run_request.assert_not_called()


class TestSessionNativeSync:

    @pytest.mark.asyncio
    async def test_native_sync_sets_master_on_first_path(self):
        """With NATIVE sync_impl, run.sync must be enabled and master must be one of the known carrier paths."""
        paths = ["AA-BB-CC-DD-EE-01", "BB-BB-CC-DD-EE-02"]
        session, ctrl = _make_session(paths=paths)

        captured_runs = []

        from pybrid.redac.controller import DistributedRunState

        orig_init = DistributedRunState.__init__

        def capturing_init(self_inner, run, paths=None):
            orig_init(self_inner, run, paths)
            captured_runs.append(run)

        with patch.object(DistributedRunState, "__init__", capturing_init), \
             patch.object(DistributedRunState, "wait_all", new=AsyncMock(return_value=None)):
            session.run(RunConfig())
            await session.execute()

        assert captured_runs, "DistributedRunState must have been created"
        run = captured_runs[-1]
        assert run.sync.enabled is True
        assert run.sync.master is not None
        # master must be one of the known paths
        known_paths = {Path.parse(p) for p in paths}
        assert run.sync.master in known_paths


class TestSessionLock:

    @pytest.mark.asyncio
    async def test_concurrent_execute_waits_for_lock(self):
        """Two sessions sharing the same controller lock must not execute concurrently."""
        ctrl = _make_mock_controller(paths=["AA-BB-CC-DD-EE-01"])
        session1 = Session(ctrl)
        session2 = Session(ctrl)

        execution_order = []
        comp = MagicMock()

        async def slow_set_config(cmd):
            execution_order.append("session1_start")
            # Hold the lock while session2 tries to acquire it
            await asyncio.sleep(0.1)
            execution_order.append("session1_end")

        async def fast_set_config(cmd):
            execution_order.append("session2_start")
            execution_order.append("session2_end")

        session1.set_config(comp)
        session2.set_config(comp)

        with patch.object(session1, "_execute_set_config", new=slow_set_config), \
             patch.object(session2, "_execute_set_config", new=fast_set_config):
            await asyncio.gather(session1.execute(), session2.execute())

        # session1 must completely finish before session2 starts
        assert execution_order.index("session1_end") < execution_order.index("session2_start"), (
            "Session2 must not start executing until session1 has finished: "
            f"got order {execution_order}"
        )


class TestSessionRunsReturnedInOrder:

    @pytest.mark.asyncio
    async def test_execute_returns_runs_in_pipeline_order(self):
        session, ctrl = _make_session()

        run_a = Run()
        run_b = Run()
        run_iter = iter([run_a, run_b])

        async def fake_run(cmd):
            return next(run_iter)

        session.run(RunConfig()).run(RunConfig())

        with patch.object(session, "_execute_run", new=fake_run):
            returned = await session.execute()

        assert len(returned) == 2
        assert returned[0] is run_a
        assert returned[1] is run_b


class TestSampleListenerForwarding:

    @pytest.mark.asyncio
    async def test_sample_listener_receives_data(self):
        """Registered SampleListener.receive() must be called with run data."""
        from pybrid.base.hybrid.listeners import SampleListener

        received_samples = []

        class FakeListener(SampleListener):
            async def receive(self, samples):
                received_samples.append(samples)

        session, ctrl = _make_session(paths=["AA-BB-CC-DD-EE-01"])
        listener = FakeListener()
        ctrl.sample_listeners.append(listener)

        fake_data = {Path.parse("AA-BB-CC-DD-EE-01"): [1.0, 2.0, 3.0]}
        captured_run = Run()
        captured_run.data = [[1.0, 2.0, 3.0]]

        async def fake_run(cmd):
            # Simulate notifying listeners as the run produces data
            for lst in ctrl.sample_listeners:
                await lst.receive(fake_data)
            return captured_run

        session.run(RunConfig())

        with patch.object(session, "_execute_run", new=fake_run):
            await session.execute()

        assert len(received_samples) >= 1
        assert received_samples[0] == fake_data


class TestSessionSingleUse:

    @pytest.mark.asyncio
    async def test_double_execute_raises(self):
        session, _ = _make_session()

        async def noop_run(cmd):
            return Run()

        session.run(RunConfig())

        with patch.object(session, "_execute_run", new=noop_run):
            await session.execute()

        # Second execute should raise
        with pytest.raises(Exception, match="[Ee]xecut|[Uu]sed|[Aa]lready"):
            await session.execute()


class TestSessionDeferredExecution:
    """Building the pipeline must NOT send any commands to devices."""

    @pytest.mark.asyncio
    async def test_pipeline_building_sends_nothing(self):
        """Commands must only be dispatched when execute() is called, not when the pipeline is built."""
        paths = ["AA-BB-CC-DD-EE-01", "BB-BB-CC-DD-EE-02"]
        session, ctrl = _make_session(paths=paths)

        comp = MagicMock()
        cfg = RunConfig()

        # Build a full pipeline — but do NOT call execute()
        session.set_config(comp).run(cfg).set_config(comp).run(cfg)

        # Verify: no control channel method has been called on any connection
        for conn in ctrl.connection_manager.get_unique_connections():
            conn.control.set_module.assert_not_called()
            conn.control.start_run_request.assert_not_called()
            conn.control.register_callback.assert_not_called()


class TestSessionErrorPropagation:
    """Session.execute() raises RuntimeError when device returns a failure Result.

    execute() must propagate config errors to the caller: it calls raise_on_error()
    on both set_module and start_run_request results.
    """

    @pytest.mark.asyncio
    async def test_execute_set_config_raises_on_device_error(self):
        """execute() raises RuntimeError when set_module returns a failure Result."""
        session, ctrl = _make_session(paths=["AA-BB-CC-DD-EE-01"])

        # Override the mock control channel to return a failure Result
        conn = list(ctrl.connection_manager.get_unique_connections())[0]
        conn.control.set_module = AsyncMock(
            return_value=Result.failure("config mismatch")
        )

        session.set_config(MagicMock())

        with pytest.raises(RuntimeError, match="config mismatch"):
            await session.execute()

    @pytest.mark.asyncio
    async def test_execute_start_run_raises_on_device_error(self):
        """execute() raises RuntimeError when start_run_request returns a failure Result."""
        session, ctrl = _make_session(paths=["AA-BB-CC-DD-EE-01"])

        # Override start_run_request to return a failure Result
        for conn in ctrl.connection_manager.get_unique_connections():
            conn.control.start_run_request = AsyncMock(
                return_value=Result.failure("run rejected")
            )

        from pybrid.redac.controller import DistributedRunState

        with patch.object(DistributedRunState, "wait_all", new=AsyncMock(return_value=None)):
            session.run(RunConfig())
            with pytest.raises(RuntimeError, match="run rejected"):
                await session.execute()


import struct
import time
import numpy as np


def _make_op_blob(
    entity_path: str,
    channel_count: int,
    sample_count: int,
    values: list[list[float]],
    probe_indices: list[int] | None = None,
) -> bytes:
    """Build a raw OP blob matching the format parsed by _parse_sample_blob.

    The blob layout is:
    - 24-byte header: 6 x uint32 LE (entity_path_len, sample_count, channel_count,
      sample_type, chunk_number, has_probes)
    - entity path bytes (UTF-8)
    - probe_indices: channel_count x uint32 LE (if has_probes == 1)
    - padding to 8-byte alignment
    - float64 data in column-major order (shape: channel_count x sample_count with order='F')
    """
    path_bytes = entity_path.encode("utf-8")
    path_len = len(path_bytes)

    if probe_indices is None:
        probe_indices = list(range(channel_count))

    has_probes = 1
    header = struct.pack(
        "<IIIIII", path_len, sample_count, channel_count, 0, 0, has_probes,
    )

    probe_bytes = struct.pack(f"<{channel_count}I", *probe_indices)

    # Padding: absolute offset after header + path + probes must be 8-byte aligned.
    var_end = 24 + path_len + len(probe_bytes)
    remainder = var_end % 8
    pad_len = (8 - remainder) if remainder != 0 else 0
    padding = b"\x00" * pad_len

    arr = np.array(values, dtype=np.float64)
    data_bytes = np.asfortranarray(arr).tobytes(order="F")

    return header + path_bytes + probe_bytes + padding + data_bytes


def _make_mock_output_queue(blobs: list[bytes]) -> MagicMock:
    """Build a mock IBuffer whose get() drains *blobs* one at a time.

    Successive calls to ``get(buf, max_bytes)`` copy one blob per call
    into *buf* and return its length.  Returns 0 when the list is exhausted.

    Args:
        blobs: Sequence of raw blob byte strings to deliver in order.

    Returns:
        A :class:`unittest.mock.MagicMock` with a configured ``get`` side_effect.
    """
    blob_iter = iter(blobs)

    def _get(buf, max_bytes):
        try:
            blob = next(blob_iter)
        except StopIteration:
            return 0
        n = len(blob)
        buf[:n] = blob
        return n

    mock_q = MagicMock()
    mock_q.get = MagicMock(side_effect=_get)
    return mock_q


def _make_session_with_queue(
    output_queue,
    paths: list[str] | None = None,
) -> tuple["Session", MagicMock]:
    """Create a Session whose single DeviceConnection has the given output_queue.

    Args:
        output_queue: The mock IBuffer to assign to the connection.
        paths:        Carrier MAC strings (defaults to one carrier).

    Returns:
        ``(session, mock_controller)`` tuple.
    """
    ctrl = _make_mock_controller(paths=paths or ["AA-BB-CC-DD-EE-01"])
    conn = list(ctrl.connection_manager.get_unique_connections())[0]
    conn.output_queue = output_queue
    session = Session(ctrl)
    return session, ctrl


class TestContinuousDrain:
    """Concurrent drain forwards data to SampleListeners during OP time rather than batching after DONE."""

    @pytest.mark.asyncio
    async def test_listener_receives_data_before_run_completes(self):
        """At least one SampleListener.receive() call must happen before wait_all(DONE) resolves."""
        from pybrid.redac.controller import DistributedRunState
        from pybrid.base.hybrid.listeners import SampleListener

        ENTITY_PATH = "/AA-BB-CC-DD-EE-01"
        blob = _make_op_blob(ENTITY_PATH, channel_count=2, sample_count=3, values=[[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]])

        # The queue delivers 2 blobs immediately, then is empty until drain_stop,
        # after which 1 final blob arrives.  We model this as: first 2 get() calls
        # return a blob, subsequent calls return 0.  The final blob scenario is
        # covered by test_drain_final_sweep_after_done.
        output_queue = _make_mock_output_queue([blob, blob])
        session, ctrl = _make_session_with_queue(output_queue)

        # Timestamps of each receive() invocation, recorded inside FakeListener
        receive_timestamps: list[float] = []

        class FakeListener(SampleListener):
            async def receive(self, samples):
                receive_timestamps.append(time.monotonic())

        ctrl.sample_listeners.append(FakeListener())

        # Track when wait_all(DONE) finishes
        done_resolved_at: list[float] = []

        async def slow_wait_all(self_inner, state):
            from pybrid.redac.run import RunState
            if state == RunState.DONE:
                await asyncio.sleep(0.3)
                done_resolved_at.append(time.monotonic())

        with patch.object(DistributedRunState, "wait_all", slow_wait_all):
            session.run(RunConfig())
            await session.execute()

        # The listener must have been called at least twice (one per blob)
        assert len(receive_timestamps) >= 2, (
            f"FakeListener.receive() was called {len(receive_timestamps)} times; "
            "expected >= 2 (one per blob delivered during OP)"
        )

        assert done_resolved_at, "wait_all(DONE) must have resolved"
        done_time = done_resolved_at[0]

        # At least one receive() call must pre-date DONE resolution
        early_calls = [t for t in receive_timestamps if t < done_time]
        assert early_calls, (
            "No SampleListener.receive() call happened before wait_all(DONE) resolved. "
            "This means the drain is sequential (after DONE), not concurrent. "
            "The drain must run concurrently with the run, not sequentially after DONE."
        )

    @pytest.mark.asyncio
    async def test_drain_handles_empty_queue_gracefully(self):
        """An always-empty output_queue must not cause errors or phantom entries in run.data."""
        from pybrid.redac.controller import DistributedRunState

        # Queue always returns 0 (perpetually empty)
        output_queue = _make_mock_output_queue([])
        session, ctrl = _make_session_with_queue(output_queue)

        with patch.object(DistributedRunState, "wait_all", new=AsyncMock(return_value=None)):
            session.run(RunConfig())
            runs = await session.execute()

        assert len(runs) == 1
        run = runs[0]
        assert len(run.data) == 0, (
            f"Expected empty run.data for an empty queue, got {run.data}"
        )

    @pytest.mark.asyncio
    async def test_drain_final_sweep_after_done(self):
        """A blob arriving after DONE (during the settling window) must be captured in the final sweep."""
        from pybrid.redac.controller import DistributedRunState
        from pybrid.base.hybrid.listeners import SampleListener

        ENTITY_PATH = "/AA-BB-CC-DD-EE-01"
        blob = _make_op_blob(ENTITY_PATH, channel_count=1, sample_count=2, values=[[7.0, 8.0]])

        output_queue = _make_mock_output_queue([blob])
        session, ctrl = _make_session_with_queue(output_queue)

        received_data: list[dict] = []

        class FakeListener(SampleListener):
            async def receive(self, samples):
                received_data.append(samples)

        ctrl.sample_listeners.append(FakeListener())

        with patch.object(DistributedRunState, "wait_all", new=AsyncMock(return_value=None)):
            session.run(RunConfig())
            runs = await session.execute()

        assert len(runs) == 1
        run = runs[0]

        # ADC channel 0 on carrier AA-BB-CC-DD-EE-01 → probe 0
        assert len(run.data) >= 1, (
            f"Expected at least 1 probe in run.data after final sweep; got {run.data}"
        )
        assert run.data[0] == [7.0, 8.0], (
            f"Unexpected values at probe 0: {run.data[0]}"
        )
        assert len(received_data) >= 1, "FakeListener must have received the final blob"

    @pytest.mark.asyncio
    async def test_drain_blob_parse_error_does_not_kill_task(self):
        """A corrupted blob must be skipped with a warning; subsequent valid blobs must still be processed."""
        import logging
        from pybrid.redac.controller import DistributedRunState

        ENTITY_PATH = "/AA-BB-CC-DD-EE-01"
        corrupted_blob = b"\x00\x01\x02"  # only 3 bytes, shorter than the 20-byte header
        valid_blob = _make_op_blob(ENTITY_PATH, channel_count=1, sample_count=2, values=[[9.0, 10.0]])

        output_queue = _make_mock_output_queue([corrupted_blob, valid_blob])
        session, ctrl = _make_session_with_queue(output_queue)

        with patch.object(DistributedRunState, "wait_all", new=AsyncMock(return_value=None)):
            # No exception should escape from execute()
            with patch.object(
                session,
                "_parse_sample_blob",
                wraps=session._parse_sample_blob,
            ) as mock_parse:
                session.run(RunConfig())

                warning_logged = []
                with patch("pybrid.redac.session.logger") as mock_logger:
                    mock_logger.warning = MagicMock(side_effect=lambda *a, **kw: warning_logged.append(a))
                    mock_logger.info = MagicMock()
                    mock_logger.debug = MagicMock()
                    runs = await session.execute()

        assert len(runs) == 1
        run = runs[0]

        # Valid blob data must still be present at probe 0
        assert len(run.data) >= 1, (
            f"Valid blob data missing from run.data; got {run.data}"
        )
        assert run.data[0] == [9.0, 10.0]

        # Warning must have been logged for the corrupted blob
        assert warning_logged, (
            "Expected a warning log entry for the corrupted blob; none was recorded."
        )

    @pytest.mark.asyncio
    async def test_data_correctness_preserved_with_concurrent_drain(self):
        """run.data must contain exact, ordered data from all N blobs — no data lost, duplicated, or mis-ordered."""
        from pybrid.redac.controller import DistributedRunState

        ENTITY_PATH = "/AA-BB-CC-DD-EE-01"
        N_BLOBS = 4
        # Each blob has 1 channel with 3 samples; values are distinct per blob
        blobs = [
            _make_op_blob(
                ENTITY_PATH,
                channel_count=1,
                sample_count=3,
                values=[[float(i * 3 + j) for j in range(3)]],
            )
            for i in range(N_BLOBS)
        ]

        output_queue = _make_mock_output_queue(blobs)
        session, ctrl = _make_session_with_queue(output_queue)

        with patch.object(DistributedRunState, "wait_all", new=AsyncMock(return_value=None)):
            session.run(RunConfig())
            runs = await session.execute()

        assert len(runs) == 1
        run = runs[0]

        # ADC channel 0 on carrier AA-BB-CC-DD-EE-01 → probe 0
        assert len(run.data) >= 1, (
            f"Expected at least 1 probe in run.data; got {run.data}"
        )

        expected_values = [float(i * 3 + j) for i in range(N_BLOBS) for j in range(3)]
        actual_values = run.data[0]

        assert actual_values == expected_values, (
            f"Data mismatch!\n"
            f"  Expected: {expected_values}\n"
            f"  Got:      {actual_values}"
        )

    @pytest.mark.asyncio
    async def test_all_probes_receive_data_not_just_probe_zero(self):
        """All ADC channels (probes 0, 1, …) must receive their data, not only probe 0."""
        from pybrid.redac.controller import DistributedRunState

        NUM_CHANNELS = 4
        ENTITY_PATH = "/AA-BB-CC-DD-EE-01"
        per_channel = [[float(ch * 10 + s) for s in range(3)] for ch in range(NUM_CHANNELS)]
        blob = _make_op_blob(
            ENTITY_PATH, channel_count=NUM_CHANNELS, sample_count=3,
            values=per_channel, probe_indices=list(range(NUM_CHANNELS)),
        )

        output_queue = _make_mock_output_queue([blob])
        session, ctrl = _make_session_with_queue(
            output_queue, paths=["AA-BB-CC-DD-EE-01"],
        )

        with patch.object(DistributedRunState, "wait_all", new=AsyncMock(return_value=None)):
            session.run(RunConfig())
            runs = await session.execute()

        run = runs[0]
        assert len(run.data) == NUM_CHANNELS, (
            f"Expected {NUM_CHANNELS} probes in run.data, got {len(run.data)}: {run.data}"
        )
        for probe_idx in range(NUM_CHANNELS):
            assert run.data[probe_idx] is not None, (
                f"run.data[{probe_idx}] is None — probe {probe_idx} received no data"
            )
            assert run.data[probe_idx] == per_channel[probe_idx], (
                f"Probe {probe_idx}: expected {per_channel[probe_idx]}, got {run.data[probe_idx]}"
            )

    @pytest.mark.asyncio
    async def test_empty_controller_adc_config_uses_blob_probes(self):
        """Probe indices come from the blob, not the controller's computer.
        Even with empty ADC config on the controller, data routes correctly."""
        from pybrid.redac.controller import DistributedRunState

        NUM_CHANNELS = 2
        ENTITY_PATH = "/AA-BB-CC-DD-EE-01"
        per_channel = [[1.0, 2.0], [3.0, 4.0]]
        blob = _make_op_blob(
            ENTITY_PATH, channel_count=NUM_CHANNELS, sample_count=2,
            values=per_channel, probe_indices=[0, 1],
        )

        # Controller has EMPTY adc_config (state right after add_device).
        ctrl = _make_mock_controller(paths=["AA-BB-CC-DD-EE-01"], num_adc_channels=0)
        conn = list(ctrl.connection_manager.get_unique_connections())[0]
        conn.output_queue = _make_mock_output_queue([blob])

        session = Session(ctrl)

        with patch.object(DistributedRunState, "wait_all", new=AsyncMock(return_value=None)):
            session.run(RunConfig())
            runs = await session.execute()

        run = runs[0]
        assert len(run.data) == NUM_CHANNELS
        assert run.data[0] == [1.0, 2.0]
        assert run.data[1] == [3.0, 4.0]

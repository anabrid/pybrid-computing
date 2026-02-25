# Copyright (c) 2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""Session — a single-use deferred pipeline for config and run commands.

A :class:`Session` buffers :class:`SetConfigCommand` and :class:`RunCommand`
objects as they are appended via the fluent :meth:`Session.set_config` /
:meth:`Session.run` API.  When :meth:`Session.execute` is called the pipeline
is dispatched **sequentially** under the controller's ``_session_lock`` so that
concurrent sessions on the same controller cannot interleave.

Typical usage::

    runs = await (
        session
        .set_config(computer)
        .run(RunConfig(op_time=2_000_000))
        .execute()
    )
"""

from __future__ import annotations

import asyncio
import logging
import struct
from abc import ABC
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional
from uuid import uuid4

import numpy as np

import pybrid.base.proto.main_pb2 as pb
from pybrid.processing.gap_fill import GapFillMode, ChunkRecord, sort_and_fill_chunks
from pybrid.redac.run import Run, RunConfig, DAQConfig, CalibrationConfig
from pybrid.redac.sync import SyncImplementationType
from pybrid.redac.entities import Path

if TYPE_CHECKING:
    from pybrid.base.hybrid.controller import BaseController
    from pybrid.base.hybrid.computer import AnalogComputer

logger = logging.getLogger(__name__)

# DecodedSampleBlobHeader layout: 5 x uint32 LE (20 bytes total).
_BLOB_HEADER_SIZE = 20
_SAMPLE_TYPE_OP = 0
_SAMPLE_TYPE_OP_END = 1


def _drain_output_queue(output_queue) -> list[bytes]:
    """Drain all decoded sample blobs from an IBuffer until it returns 0 bytes."""
    blobs: list[bytes] = []
    buf = bytearray(4 * 1024 * 1024)  # 4 MB scratch
    while True:
        n = output_queue.get(buf, len(buf))
        if n == 0:
            break
        blobs.append(bytes(buf[:n]))
    return blobs


class SessionCommand(ABC):
    pass


@dataclass
class SetConfigCommand(SessionCommand):
    """Exactly one of *computer* or *bundle* must be set."""

    computer: Optional["AnalogComputer"] = None
    bundle: Optional[pb.ConfigBundle] = None


@dataclass
class RunCommand(SessionCommand):
    config: RunConfig = field(default_factory=RunConfig)
    daq: Optional[DAQConfig] = None
    entities: Optional[set[Path]] = None
    timeout: Optional[float] = None


class Session:
    """Single-use pipeline that buffers config and run commands and executes
    them sequentially under the controller's session lock.

    A session is **single-use**: calling :meth:`execute` a second time raises
    :class:`RuntimeError`.
    """

    def __init__(self, controller: "BaseController") -> None:
        self._controller = controller
        self._pipeline: list[SessionCommand] = []
        self.runs: list[Run] = []
        self._executed: bool = False

    @property
    def controller(self) -> "BaseController":
        return self._controller

    def set_config(self, computer: "AnalogComputer") -> "Session":
        """:returns: ``self`` so calls can be chained."""
        self._pipeline.append(SetConfigCommand(computer=computer))
        return self

    def set_config_bundle(self, bundle: pb.ConfigBundle) -> "Session":
        """:returns: ``self`` so calls can be chained."""
        self._pipeline.append(SetConfigCommand(bundle=bundle))
        return self

    def run(
        self,
        config: Optional[RunConfig] = None,
        daq: Optional[DAQConfig] = None,
        *,
        entities: Optional[set[Path]] = None,
        timeout: Optional[float] = None,
    ) -> "Session":
        """:returns: ``self`` so calls can be chained."""
        if config is None:
            config = RunConfig()
        self._pipeline.append(
            RunCommand(config=config, daq=daq, entities=entities, timeout=timeout)
        )
        return self

    async def execute(self, *, timeout: Optional[float] = None) -> list[Run]:
        """Execute all buffered pipeline commands sequentially.

        Acquires the controller's ``_session_lock`` for the full duration so
        that two :class:`Session` objects sharing the same controller cannot
        interleave.

        :raises RuntimeError: If called more than once on the same instance.
        """
        async def _run_pipeline() -> None:
            async with self._controller._session_lock:
                if self._executed:
                    raise RuntimeError(
                        "Session.execute() has already been called.  "
                        "Sessions are single-use; create a new Session for each execution."
                    )
                self._executed = True
                for cmd in self._pipeline:
                    if isinstance(cmd, SetConfigCommand):
                        await self._execute_set_config(cmd)
                    elif isinstance(cmd, RunCommand):
                        run = await self._execute_run(cmd)
                        self.runs.append(run)

        if timeout is not None:
            async with asyncio.timeout(timeout):
                await _run_pipeline()
        else:
            await _run_pipeline()

        return self.runs

    async def _execute_set_config(self, cmd: SetConfigCommand) -> None:
        """Upload configuration to all unique device connections.

        In proxy mode multiple carrier paths share one DeviceConnection;
        get_unique_connections collapses those so the bundle is sent exactly
        once per physical channel.
        """
        if cmd.computer is not None:
            serializer_cls = self._controller.computer.get_serializer_implementation()
            serializer = serializer_cls()
            configs = serializer.serialize(cmd.computer)
            bundle = pb.ConfigBundle(configs=configs)
        elif cmd.bundle is not None:
            bundle = cmd.bundle
        else:
            logger.warning("SetConfigCommand has neither computer nor bundle; skipping.")
            return

        unique_conns = self._controller.connection_manager.get_unique_connections()

        from google.protobuf.json_format import MessageToJson
        logger.debug(
            "_execute_set_config: sending %d config entries to %d connection(s):\n%s",
            len(bundle.configs),
            len(unique_conns),
            MessageToJson(bundle, indent=2),
        )

        for conn in unique_conns:
            if conn.control is None:
                raise NotImplementedError(
                    "Sending configuration requires the native C++ extension "
                    "(pybrid-computing-native). The control channel is not available "
                    "in this environment."
                )
            result = await conn.control.set_config_bundle(bundle)
            result.raise_on_error()

    async def _execute_run(self, cmd: RunCommand) -> Run:
        """Execute a single run described by *cmd* and return the completed Run."""
        from pybrid.redac.controller import DistributedRunState
        from pybrid.redac.run import RunState
        from dataclasses import replace

        # Default timeout adds headroom for cross-carrier calibration.
        _RUN_TIMEOUT_HEADROOM_SECS = 10.0
        run_timeout = cmd.timeout
        if run_timeout is None:
            run_timeout = cmd.config.op_time / 1e9 + _RUN_TIMEOUT_HEADROOM_SECS

        run = Run(
            config=cmd.config,
            daq=cmd.daq if cmd.daq is not None else DAQConfig(),
        )
        self._controller.runs[run.id_] = run
        logger.info("Session: starting run %s (timeout=%.1fs).", run.id_, run_timeout)

        all_paths: list[Path] = list(self._controller.connection_manager.connections.keys())
        if cmd.entities is not None:
            involved_paths: list[Path] = [p for p in all_paths if p in cmd.entities]
        else:
            involved_paths = all_paths

        if not involved_paths:
            raise ValueError(
                "No connections are involved in the run. "
                "cmd.entities may not match any registered paths."
            )

        run.sync.group = run.partition.id

        # In NATIVE mode the first carrier generates the SYNC pulse.
        # For USBSPI: no sync master is set; all devices wait for external trigger.
        first_path = involved_paths[0]

        if self._controller.sync_impl == SyncImplementationType.NATIVE:
            if not run.calibration.enabled:
                raise NotImplementedError(
                    "NATIVE sync requires calibration for implicit synchronisation."
                )
            run.sync.enabled = True
            run.sync.master = first_path

            if run.calibration.enabled and run.calibration.leader is None:
                run.calibration = replace(run.calibration, leader=first_path)

        run_state = DistributedRunState(run, involved_paths)

        involved_connections: dict[Path, object] = {}
        for path in involved_paths:
            conn = self._controller.connection_manager.get_connection(path)
            involved_connections[path] = conn

        # In proxy mode, multiple paths share one connection; collapse by identity.
        unique_involved_conns = set(involved_connections.values())

        involved_paths_set = set(involved_paths)

        def _make_state_callback(conn_ref, path_list: list[Path]):
            """Create a run-state-change callback closing over *path_list*.

            If the message carries an entity path (proxy mode), only the
            matching carrier path is tracked.  Otherwise all paths on this
            connection are tracked.
            """
            def _callback(msg: pb.MessageV1) -> None:
                change = msg.run_state_change_message
                if change.run.id != str(run.id_):
                    return
                new_state = RunState.from_pb(change.new_)

                entity_path_str = (
                    change.entity.path if change.HasField("entity") else ""
                )
                if entity_path_str:
                    target_path = Path.parse(entity_path_str).to_root()
                    if target_path in involved_paths_set:
                        run_state.track(target_path, new_state, change.reason)
                    else:
                        logger.warning(
                            "RunStateChangeMessage entity %s not in tracked paths",
                            entity_path_str,
                        )
                else:
                    for p in path_list:
                        run_state.track(p, new_state, change.reason)
            return _callback

        conn_to_paths: dict = {}
        for path, conn in involved_connections.items():
            conn_id = id(conn)
            if conn_id not in conn_to_paths:
                conn_to_paths[conn_id] = (conn, [])
            conn_to_paths[conn_id][1].append(path)

        # Data messages (OP / OP_END) are decoded by the C++ SampleDecodingDataChannel
        # and placed into the IBuffer output queue; we drain them after DONE.
        state_field = pb.MessageV1.RUN_STATE_CHANGE_MESSAGE_FIELD_NUMBER

        for _conn_id, (conn, paths) in conn_to_paths.items():
            if conn.control is None:
                raise NotImplementedError(
                    "Executing a run requires the native C++ extension "
                    "(pybrid-computing-native). The control channel is not available "
                    "in this environment."
                )
            conn.control.register_callback(state_field, _make_state_callback(conn, paths))

        try:
            pb_run_config = pb.RunConfig(
                ic_time=pb.Time(value=int(run.config.ic_time), prefix=pb.Prefix.NANO),
                op_time=pb.Time(value=int(run.config.op_time), prefix=pb.Prefix.NANO),
                halt_on_overload=run.config.halt_on_overload,
                write_run_state_changes=True,
                streaming=run.daq.sample_op or run.daq.sample_op_end,
            )
            pb_daq_config = pb.DaqConfig(
                num_channels=run.daq.num_channels,
                sample_rate=run.daq.sample_rate,
                sample_op=run.daq.sample_op,
                sample_op_end=run.daq.sample_op_end,
            )
            pb_sync_config = pb.SyncConfig(
                enabled=run.sync.enabled,
                master=(
                    None
                    if run.sync.master is None
                    else pb.EntityId(path=str(run.sync.master))
                ),
                group=run.sync.group,
            )
            pb_calibration_config = pb.CalibrationConfig(
                enabled=run.calibration.enabled,
                leader=(
                    None
                    if run.calibration.leader is None
                    else pb.EntityId(path=str(run.calibration.leader))
                ),
            )
            run_command = pb.StartRunCommand(
                run=pb.Run(id=str(run.id_), chunk=0),
                run_config=pb_run_config,
                daq_config=pb_daq_config,
                sync_config=pb_sync_config,
                calibration_config=pb_calibration_config,
            )

            from google.protobuf.json_format import MessageToJson
            logger.debug(
                "_execute_run: StartRunCommand:\n%s",
                MessageToJson(run_command, indent=2),
            )

            # Proxies fan-out to all carriers when no entity ID is set.
            send_tasks = [
                conn.control.start_run_request(run_command)
                for conn in unique_involved_conns
            ]
            results = await asyncio.gather(*send_tasks)
            for result in results:
                result.raise_on_error()

            chunk_buffer: list[ChunkRecord] = []
            drain_stop_event = asyncio.Event()
            drain_task = asyncio.create_task(
                self._continuous_drain(
                    unique_involved_conns, run, drain_stop_event, chunk_buffer,
                )
            )

            # Syncing across the REDAC may take longer, so wait until all carriers
            # reach TAKE_OFF before starting the run timeout.
            async with asyncio.timeout(run_timeout):
                await run_state.wait_all(RunState.TAKE_OFF)

            try:
                async with asyncio.timeout(run_timeout):
                    await run_state.wait_all(RunState.DONE)
            finally:
                # Signal drain to stop and await it — always run, even on timeout or error.
                # This ensures the drain task is never orphaned.
                drain_stop_event.set()
                try:
                    await drain_task
                except asyncio.CancelledError:
                    pass

                gap_fill_mode = getattr(
                    self._controller, "gap_fill_mode", GapFillMode.INTERPOLATE,
                )
                self._assemble_run_data(chunk_buffer, run, gap_fill_mode)

                for listener in self._controller.sample_listeners:
                    try:
                        await listener.on_run_complete()
                    except Exception:
                        logger.warning(
                            "on_run_complete raised on listener %r",
                            listener,
                            exc_info=True,
                        )

        finally:
            for _conn_id, (conn, _paths) in conn_to_paths.items():
                conn.control.unregister_callback(state_field)

        return run

    async def _continuous_drain(
        self,
        connections: set,
        run: Run,
        stop_event: asyncio.Event,
        chunk_buffer: list[ChunkRecord],
        poll_interval: float = 0.05,
    ) -> None:
        """Continuously drain output queues, buffer chunks, and forward OP blobs to listeners.

        When *stop_event* is set (run completed), performs a final drain after
        a 150 ms settling delay and then returns.
        """
        buf = bytearray(1024 * 1024)

        while not stop_event.is_set():
            await asyncio.sleep(poll_interval)
            for conn in connections:
                if conn.output_queue is None:
                    continue
                while True:
                    n = conn.output_queue.get(buf, len(buf))
                    if n == 0:
                        break
                    blob = bytes(buf[:n])
                    try:
                        await self._parse_sample_blob(blob, run, chunk_buffer)
                    except Exception:
                        logger.warning(
                            "Failed to parse sample blob during continuous drain",
                            exc_info=True,
                        )

        # Allow in-flight data to settle before the final sweep.
        await asyncio.sleep(0.15)
        for conn in connections:
            if conn.output_queue is None:
                continue
            blobs = _drain_output_queue(conn.output_queue)
            for blob in blobs:
                try:
                    await self._parse_sample_blob(blob, run, chunk_buffer)
                except Exception:
                    logger.warning(
                        "Failed to parse sample blob during final sweep",
                        exc_info=True,
                    )

    async def _parse_sample_blob(
        self,
        blob: bytes,
        run: Run,
        chunk_buffer: list[ChunkRecord],
    ) -> None:
        """Parse a single decoded sample blob, buffer it, and forward OP blobs to listeners."""
        if len(blob) < _BLOB_HEADER_SIZE:
            logger.warning("Ignoring sample blob shorter than header (%d bytes).", len(blob))
            return

        # Parse 20-byte header: entity_path_len, sample_count, channel_count,
        # sample_type, chunk_number.
        (
            entity_path_len, sample_count, channel_count, sample_type, chunk_number,
        ) = struct.unpack_from("<IIIII", blob, 0)

        if channel_count == 0 or sample_count == 0:
            return

        path_start = _BLOB_HEADER_SIZE
        path_end = path_start + entity_path_len
        entity_path_str = blob[path_start:path_end].decode("utf-8")

        # Padding to 8-byte alignment after entity path.
        data_offset = path_end
        remainder = data_offset % 8
        if remainder != 0:
            data_offset += 8 - remainder

        # Data is column-major from the wire (each sample point groups all channels):
        #   [ch0_s0, ch1_s0, ..., ch0_s1, ch1_s1, ...]
        # Reshape with order="F" for zero-copy: numpy sets strides without moving data.
        num_samples = sample_count * channel_count
        samples_raw = np.frombuffer(
            blob, dtype=np.float64, count=num_samples, offset=data_offset
        )
        samples = samples_raw.reshape((channel_count, sample_count), order="F")

        chunk_buffer.append(ChunkRecord(
            chunk_number=chunk_number,
            entity_path=entity_path_str,
            sample_type=sample_type,
            channel_count=channel_count,
            samples=samples.copy(),
        ))

        if sample_type == _SAMPLE_TYPE_OP:
            entity_path = Path(entity_path_str.split("/"))
            samples_dict: dict[Path, list[float]] = {}
            for i in range(channel_count):
                channel_path = entity_path.join(f"ADC{i}")
                samples_dict[channel_path] = samples[i].tolist()

            for listener in self._controller.sample_listeners:
                await listener.receive(samples_dict)

    def _assemble_run_data(
        self,
        chunk_buffer: list[ChunkRecord],
        run: Run,
        gap_fill_mode: GapFillMode,
    ) -> bool:
        """Sort, fill, and assemble buffered chunks into run.data / run.final_values.

        Returns ``True`` if any gap was detected.
        """
        from collections import defaultdict

        if not chunk_buffer:
            return False

        groups: dict[tuple[str, int], list[ChunkRecord]] = defaultdict(list)
        for cr in chunk_buffer:
            groups[(cr.entity_path, cr.sample_type)].append(cr)

        any_gap = False
        any_reorder = False

        for (entity_path_str, sample_type), group_chunks in groups.items():
            filled, gap_detected, reordered = sort_and_fill_chunks(
                group_chunks, gap_fill_mode,
            )
            any_gap = any_gap or gap_detected
            any_reorder = any_reorder or reordered

            entity_path = Path(entity_path_str.split("/"))

            if sample_type == _SAMPLE_TYPE_OP:
                for i in range(filled[0].channel_count if filled else 0):
                    channel_path = entity_path.join(f"ADC{i}")
                    for cr in filled:
                        run.data[channel_path].extend(cr.samples[i].tolist())

            elif sample_type == _SAMPLE_TYPE_OP_END:
                if filled:
                    last_cr = filled[-1]
                    carrier_path = entity_path.to_root()
                    num_clusters = self._controller._clusters_per_carrier.get(
                        carrier_path, 3,
                    )
                    num_mblocks = num_clusters * 2
                    flat = last_cr.samples.ravel()
                    for block_idx in range(num_mblocks):
                        block_path = entity_path.join(
                            f"{block_idx // 2}"
                        ).join(f"M{block_idx % 2}")
                        for output_idx in range(8):
                            fvi = block_idx * 8 + output_idx
                            if fvi < len(flat):
                                run.final_values[
                                    block_path.join(str(output_idx))
                                ] = flat[fvi]

        if any_reorder:
            logger.warning(
                "Sample chunks for run %s arrived out of order — "
                "reordered during assembly.",
                run.id_,
            )

        if any_gap:
            mode_name = gap_fill_mode.name
            logger.warning(
                "Data chunk sequence gap detected during run %s — "
                "missing chunks were filled (%s mode). Check network "
                "stability or consider using a proxy closer to the device.",
                run.id_,
                mode_name,
            )

        return any_gap

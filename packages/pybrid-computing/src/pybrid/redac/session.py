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
import copy
from abc import ABC
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional
from uuid import uuid4

import numpy as np

import pybrid.base.proto.main_pb2 as pb
from pybrid.redac.run import Run, RunConfig, DAQConfig
from pybrid.redac.entities import Path
from pybrid.util.updater import UpdaterUtils

if TYPE_CHECKING:
    from pybrid.base.hybrid.controller import BaseController
    from pybrid.base.hybrid.computer import AnalogComputer

logger = logging.getLogger(__name__)

# DecodedSampleBlobHeader layout: 6 x uint32 LE (24 bytes total).
_BLOB_HEADER_SIZE = 24
_SAMPLE_TYPE_OP = 0
_SAMPLE_TYPE_OP_END = 1


@dataclass(frozen=True, slots=True)
class ChunkRecord:
    """A single decoded sample chunk with metadata.

    Attributes:
        chunk_number: Sequence number from the protobuf message.
        entity_path: Entity path string (e.g. ``"/MAC/Carrier0"``).
        sample_type: Sample type: 0 = OP, 1 = OP_END.
        channel_count: Number of channels in the samples array.
        samples: Decoded samples, shape ``(channel_count, sample_count)``.
        probe_indices: Per-channel probe index from blob (None if not present).
    """

    chunk_number: int
    entity_path: str
    sample_type: int
    channel_count: int
    samples: np.ndarray
    probe_indices: tuple[int, ...] | None = None


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
    module: pb.Module

@dataclass
class RunCommand(SessionCommand):
    config: RunConfig = field(default_factory=RunConfig)
    daq: Optional[DAQConfig] = None
    entities: Optional[set[Path]] = None
    timeout: Optional[float] = None

@dataclass
class CalibrateCommand(SessionCommand):
    leader: str
    math: bool
    gain: bool
    offset: bool

@dataclass
class FirmwareUpdateCommand(SessionCommand):
    binary: bytearray
    sha256: bytes
    reboot_grace: float = 2.0
    reconnect_timeout: float = 20.0
    verbose: bool = False

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

        serializer_cls = computer.get_serializer()
        serializer = serializer_cls()
        module = serializer.serialize(computer)
        return self.set_module(module, raw=True)
    
    def set_module(self, module: pb.Module, raw: bool = False) -> "Session":
        """Deserialize a protobuf Module into the controller's computer model
        and buffer the resulting config.

        :returns: ``self`` so calls can be chained.
        """
        if raw:
            self._pipeline.append(SetConfigCommand(module=module))
        else:
            computer = copy.deepcopy(self._controller.computer)
            deserializer = computer.get_deserializer()(computer)
            deserializer.deserialize(module)
            self.set_config(computer)
        return self
    
    def set_firmware(
        self,
        firmware: str | bytearray,
        *,
        reboot_grace: float = 2.0,
        reconnect_timeout: float = 20.0,
        verbose: bool = False,
    ) -> "Session":
        """Stores a (binary) firmware file that is to be uploaded and applied to
        the computer before any next step.

        :param firmware: Either a path to a firmware file or an in-memory
            ``bytearray`` payload.
        :param reboot_grace: Seconds to wait after a successful commit before
            attempting to reconnect to each device (direct mode only).
        :param reconnect_timeout: Total deadline, in seconds, for every per-device
            reconnect after the reboot grace (direct mode only).
        :param verbose: If ``True``, print progress information to stderr
            during upload, verification, and commit.
        :returns: ``self`` so calls can be chained.
        """
        use_fw = firmware
        fw_sha256 = ""
        if isinstance(firmware, str):
            use_fw, fw_sha256 = UpdaterUtils.read_to_bin(firmware)
        elif isinstance(firmware, bytearray):
            fw_sha256 = UpdaterUtils.sha256(firmware)
        else:
            raise Exception("Unknown firmware data format")

        self._pipeline.append(FirmwareUpdateCommand(
            binary=use_fw,
            sha256=fw_sha256,
            reboot_grace=reboot_grace,
            reconnect_timeout=reconnect_timeout,
            verbose=verbose,
        ))

        return self
    
    def calibrate(self, leader: str = "", math: bool = False, gain: bool = True, offset: bool = True) -> "Session":
        """:returns: ``self`` so calls can be chained."""

        use_leader = leader
        if len(use_leader) == 0:
            # no leader given -> use first device in the controller by default
            use_leader = self.controller.computer.carriers[0].path.to_mac()

        self._pipeline.append(CalibrateCommand(leader=use_leader, math=math, gain=gain, offset=offset))
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
                    elif isinstance(cmd, CalibrateCommand):
                        await self._execute_calibrate(cmd)
                    elif isinstance(cmd, RunCommand):
                        run = await self._execute_run(cmd)
                        self.runs.append(run)
                    elif isinstance(cmd, FirmwareUpdateCommand):
                        await self._execute_upload(cmd)
                    else: 
                        print(f"[Session] Skipping unknown command of type {type(cmd).__name__}")

        if timeout is not None:
            async with asyncio.timeout(timeout):
                await _run_pipeline()
        else:
            await _run_pipeline()

        return self.runs

    async def _execute_calibrate(self, cmd: CalibrateCommand) -> None:
        """Run calibration over all devices.

        When *leader* is empty, defaults to the first registered carrier path.
        """

        leader = cmd.leader
        if not leader:
            all_paths = list(self._controller.connection_manager.connections.keys())
            if all_paths:
                leader = str(all_paths[0])

        unique_conns = self._controller.connection_manager.get_unique_connections()

        for conn in unique_conns:
            if conn.control is None:
                raise NotImplementedError(
                    "Running calibration requires the native C++ extensions "
                    "(pybrid-computing-native). The control channel is not available "
                    "in this environment."
                )
            result = await conn.control.calibrate(leader, cmd.math, cmd.gain, cmd.offset, 
                timeout=10.0)
            result.raise_on_error()

    async def _execute_set_config(self, cmd: SetConfigCommand) -> None:
        """Upload configuration to all unique device connections.

        In proxy mode multiple carrier paths share one DeviceConnection;
        get_unique_connections collapses those so the module is sent exactly
        once per physical channel.
        """

        module = cmd.module

        # distribute modules to devices
        unique_conns = self._controller.connection_manager.get_unique_connections()

        from google.protobuf.json_format import MessageToJson
        logger.debug(
            "_execute_set_config: sending %d config entries to %d connection(s):\n%s",
            len(module.items),
            len(unique_conns),
            MessageToJson(module, indent=2),
        )

        for conn in unique_conns:
            if conn.control is None:
                raise NotImplementedError(
                    "Sending configuration requires the native C++ extension "
                    "(pybrid-computing-native). The control channel is not available "
                    "in this environment."
                )
            result = await conn.control.set_module(module)
            result.raise_on_error()

    async def _execute_upload(self, cmd: FirmwareUpdateCommand) -> None:
        """Execute the firmware upload in stages (per device, sequentially).

        Runs ``update_begin``, ``update_write_full``, ``update_verify`` and
        ``update_commit`` on every unique device connection, then sleeps for
        ``cmd.reboot_grace`` seconds and reconnects each control channel so a
        follow-up ``set_config`` / ``run`` on the same controller sees the
        freshly booted firmware. The UDP data transport is rebuilt in-place
        after every reconnect so streaming resumes without a full
        ``DeviceConnection`` rebuild.

        When a real proxy sits in front of the devices its
        ``UpdateResponse.success`` is already gated on its backends being
        healthy, so the reconnect below degenerates to a fast tear-down /
        reconnect of the still-alive client socket.
        """
        logger.debug(
            "Firmware size: %d, SHA256: %s, uploading...",
            len(cmd.binary), cmd.sha256,
        )

        unique_conns = list(
            self._controller.connection_manager.get_unique_connections()
        )
        try:
            # phase 1: upload firmware to devices
            for connection in unique_conns:
                control = connection.control

                host = control.remote_host
                port = control.remote_port
                logger.debug("Uploading firmware to %s:%s", host, port)

                max_chunk_size = await control.update_begin(
                    len(cmd.binary), cmd.sha256,
                    verbose=cmd.verbose,
                )
                logger.debug("\tMaximum chunk size: %s", max_chunk_size)

                res = await control.update_write_full(
                    len(cmd.binary), max_chunk_size, cmd.binary,
                    verbose=cmd.verbose,
                )
                res.raise_on_error()
                logger.debug("\tUpload successful!")

            # phase 2: verify on all devices
            for connection in unique_conns:
                control = connection.control
                res = await control.update_verify(verbose=cmd.verbose)
                res.raise_on_error()
                logger.debug("Verification successfull on %s", control.remote_host)

            # phase 3: commit update on all devices
            for connection in unique_conns:
                control = connection.control
                res = await control.update_commit(verbose=cmd.verbose)
                res.raise_on_error()
                logger.debug("Commit done for %s", control.remote_host)

        except (KeyboardInterrupt, Exception, asyncio.CancelledError):
            # Best-effort abort broadcast on any failure, user interruption, or
            # task cancellation; the bare ``raise`` preserves CancelledError
            # semantics so the surrounding task still terminates.
            for connection in unique_conns:
                try:
                    await connection.control.update_abort()
                except Exception as abort_exc:
                    logger.warning(
                        "update_abort failed on %s: %s", connection, abort_exc,
                    )
            raise

        # Cache each connection's endpoint while it is still connected so we
        # can include it in the error message even after the transport has
        # dropped (remote_host/remote_port clear on disconnect).
        endpoints = [
            (connection.control.remote_host, connection.control.remote_port)
            for connection in unique_conns
        ]

        # Wait once for the device(s) to reboot, then check each unique
        # control channel: if it dropped, the device rebooted under us in
        # direct mode and we have to reconnect; if it survived, a proxy
        # handled the reconnect on our behalf and tearing it down here would
        # break the proxy session. Callers on slower links can raise
        # ``reboot_grace`` to widen the margin against the drop/check race.
        await asyncio.sleep(cmd.reboot_grace)

        for (host, port), connection in zip(endpoints, unique_conns):
            control = connection.control
            if control.is_connected:
                # The channel survived the reboot grace: either we're behind
                # a proxy that handled the reconnect on our behalf, or the
                # device didn't actually drop the connection. Either way no
                # client-side reconnect is needed for this connection.
                continue

            reconnected = await control.reconnect(timeout=cmd.reconnect_timeout)
            if not reconnected:
                raise RuntimeError(
                    f"Failed to reconnect to backend {host}:{port} "
                    f"after firmware update (timeout={cmd.reconnect_timeout}s)"
                )

            data = connection.data
            if data is not None:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, data.reconnect)

    async def _execute_run(self, cmd: RunCommand) -> Run:
        """Execute a single run described by *cmd* and return the completed Run."""
        from pybrid.redac.controller import DistributedRunState
        from pybrid.redac.run import RunState

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
        first_path = involved_paths[0]
        run.sync.enabled = True
        run.sync.master = first_path

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
            run_command = pb.StartRunCommand(
                run=pb.Run(id=str(run.id_), chunk=0),
                run_config=pb_run_config,
                daq_config=pb_daq_config,
                sync_config=pb_sync_config
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

                self._assemble_run_data(chunk_buffer, run)

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

        (
            entity_path_len, sample_count, channel_count,
            sample_type, chunk_number, has_probes,
        ) = struct.unpack_from("<IIIIII", blob, 0)

        if channel_count == 0 or sample_count == 0:
            return

        path_start = _BLOB_HEADER_SIZE
        path_end = path_start + entity_path_len
        entity_path_str = blob[path_start:path_end].decode("utf-8")

        # Read probe indices (channel_count x uint32) if present.
        probe_indices: tuple[int, ...] | None = None
        probe_end = path_end
        if has_probes:
            probe_bytes = channel_count * 4  # uint32
            probe_end = path_end + probe_bytes
            probe_indices = struct.unpack_from(
                f"<{channel_count}I", blob, path_end,
            )

        # Padding to 8-byte alignment after entity path + probe indices.
        data_offset = probe_end
        remainder = data_offset % 8
        if remainder != 0:
            data_offset += 8 - remainder

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
            probe_indices=probe_indices,
        ))

        if sample_type == _SAMPLE_TYPE_OP:
            entity_path = Path.parse(entity_path_str)
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
    ) -> None:
        """Sort and assemble buffered chunks into run.data / run.final_values.

        Builds a probe-indexed list: ``run.data[probe_index] = [samples]``.
        Probe indices come from the decoded blob (embedded by C++ from
        ``DaqData.channels[i].probe()``).
        """
        from collections import defaultdict

        if not chunk_buffer:
            return

        groups: dict[tuple[str, int], list[ChunkRecord]] = defaultdict(list)
        for cr in chunk_buffer:
            groups[(cr.entity_path, cr.sample_type)].append(cr)

        probe_data: dict[int, list[float]] = defaultdict(list)
        any_reorder = False

        for (entity_path_str, sample_type), group_chunks in groups.items():
            sorted_chunks = sorted(group_chunks, key=lambda c: c.chunk_number)
            reordered = any(
                a.chunk_number != b.chunk_number
                for a, b in zip(group_chunks, sorted_chunks)
            )
            any_reorder = any_reorder or reordered

            entity_path = Path.parse(entity_path_str)

            if sample_type == _SAMPLE_TYPE_OP:
                ref_chunk = sorted_chunks[0] if sorted_chunks else None
                if ref_chunk is None:
                    continue

                for i in range(ref_chunk.channel_count):
                    if ref_chunk.probe_indices is None:
                        raise Exception("Probe index is not set!")
                    probe_idx = ref_chunk.probe_indices[i]
                    
                    for cr in sorted_chunks:
                        probe_data[probe_idx].extend(cr.samples[i].tolist())

            elif sample_type == _SAMPLE_TYPE_OP_END:
                if sorted_chunks:
                    last_cr = sorted_chunks[-1]
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

        if probe_data:
            max_probe = max(probe_data.keys())
            run.data = [None] * (max_probe + 1)
            for idx, samples in probe_data.items():
                run.data[idx] = samples

        if any_reorder:
            logger.warning(
                "Sample chunks for run %s arrived out of order — "
                "reordered during assembly.",
                run.id_,
            )

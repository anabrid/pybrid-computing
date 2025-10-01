# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later
import array
import asyncio
import logging
import socket
import typing
import warnings
from collections import defaultdict
from copy import deepcopy
from dataclasses import replace
from ipaddress import IPv4Address
from uuid import UUID
import struct
import numpy as np
from google.protobuf.json_format import MessageToJson, MessageToDict

from pybrid.base.transport import TCPTransport
from pybrid.redac.carrier import Carrier
from pybrid.redac.computer import REDAC
from pybrid.redac.device import Device
from pybrid.redac.entities import Entity, Path, UnknownEntityTypeError
from pybrid.redac.port import get_free_udp_port
from pybrid.redac.protocol.protocol import Protocol
from pybrid.redac.run import Run, RunState, RunError
from pybrid.redac.sync import Sync, SyncMode, SyncConfig
from pybrid.base.transport.tcp import TCPTransport
from pybrid.base.transport.udp import UDPTransport

import pybrid.base.proto.main_pb2 as pb
logger = logging.getLogger(__name__)


class DistributedRunState:
    #: A dictionary tracking each possible RunState for each involved carrier
    _states: dict[Path, dict[RunState, asyncio.Semaphore]]
    #: The run which state we are tracking
    run: Run
    #: The run once it's done
    _any_error_future: asyncio.Future

    def __init__(self, run, paths: typing.Optional[typing.Iterable[Path]] = None):
        self.run = run
        self._any_error_future = asyncio.Future()
        # Adding initial paths using the add_paths method
        self._states = {}
        if paths:
            self.add_paths(*paths)

    def get_involved_paths(self) -> typing.Iterable[Path]:
        return self._states.keys()

    def track(self, path: Path, state: RunState, reason: str | None = None):
        self._states[path][state].set()
        if state == RunState.ERROR and not self._any_error_future.done():
            self._any_error_future.set_exception(RunError(f"Error on entity {path}: {reason or 'Unknown Error'}"))

    def status(self, state: RunState):
        reached = []
        notreached = []
        for entity in self._states.values():
            if entity[state].locked():
                notreached.append(entity)
            else:
                reached.append(entity)
        return reached, notreached

    async def wait_all(self, state: RunState):
        """
        Wait for all entities to reach the target state.

        Raises `RunError` if any entity enters `RunState.ERROR` while waiting.
        """
        waiting_for = {asyncio.create_task(states[state].wait()): entity for entity, states in self._states.items()}
        try:
            while waiting_for:
                # Wait for the next entity to reach the target state.
                # This is short-circuited by self._any_error_future in case any entity enters RunState.ERROR
                waiting_or_error = [self._any_error_future, *waiting_for]
                done, _ = await asyncio.wait(waiting_or_error, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    if exc := task.exception():
                        # Any entity entered RunState.ERROR or there was another error while waiting
                        raise exc
                    else:
                        # Entity reached target state without issue.
                        waiting_for.pop(task)
        except asyncio.CancelledError:
            # We have been cancelled, most like due to an externally enforced timeout.
            # Report which entities did not reach the target state.
            # Convert to a TimeoutError, otherwise asyncio.timeout() and asyncio.wait_for() drop the error description.
            raise asyncio.TimeoutError(f"Entities {list(map(str, waiting_for.values()))} did not reach {state}.")
        finally:
            # Clean-up tasks which may not have finished.
            for task in waiting_for:
                task.cancel()
            await asyncio.gather(*waiting_for, return_exceptions=True)

    def add_paths(self, *paths: Path):
        """
        Adds multiple Paths to the _states dictionary with initialized states.
        Accepts a variable number of Path arguments.
        """
        for path in paths:
            if path in self._states:
                raise ValueError(f"Path {path} is already being tracked.")
            self._states[path] = {state: asyncio.Event() for state in RunState}

class DeviceEntry:
    address: IPv4Address
    protocol: Protocol
    path: Path

    def __init__(self, path: Path, address: IPv4Address, protocol: Protocol):
        self.path = path
        self.address = address
        self.protocol = protocol

    async def stop(self):
        if self.protocol is not None:
            await self.protocol.stop()

    def get_remote_ip(self) -> IPv4Address:
        return self.address

class Controller:
    """
    Abstraction of the REDAC hybrid controller.

    The hybrid controller is an interface to all relevant functions to configure and control the REDAC.
    It also collects all :class:`Run` instances started with it.

    The controller object also holds references to the underlying protocol and transport objects and manages them.
    """

    #: Representation of the current configuration of the analog computer.
    computer: REDAC
    #: Dictionary of all managed devices identified by their unique entity path.
    #: TODO: Remove in favor of protocols below.
    devices: dict[Path, DeviceEntry]
    #: Dictionary of protocol connections mapped to entity paths they manage
    protocols: dict[Protocol, set[Path]]
    #: List of all runs started by this controller.
    runs: dict[UUID, Run]
    _raw_entity_dict: dict
    _ongoing_runs: dict[UUID, DistributedRunState]

    sync: typing.Optional[Sync]
    standalone: bool

    def __init__(self, standalone: bool = False):
        self.computer = REDAC(entities=[])
        self.devices = dict()
        self.protocols = defaultdict(set)
        self.runs = dict()
        self._raw_entity_dict = dict()
        self._ongoing_runs = dict()

        self.sync = None
        self.standalone = standalone
        self._callbacks: dict[int, tuple[typing.Callable, list, dict]] = dict()


    def register_callback(self, msg_type: int, callback: typing.Callable, extra_args=None, extra_kwargs=None):
        previous = self._callbacks.get(msg_type, None)
        self._callbacks[msg_type] = (callback, extra_args or list(), extra_kwargs or dict())
        return previous

    async def __aenter__(self):
        # Devices are already started in add_device
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        for device in self.devices.values():
            await device.stop()

    @classmethod
    def get_protocol_implementation(cls):
        """Returns the specific :class:`.Protocol` implementation by this device"""
        return Protocol

    @classmethod
    def get_run_implementation(cls) -> typing.Type[Run]:
        """Returns the specific :class:`.Run` implementation used by the REDAC."""
        return Run

    def enable_sync(self):
        if self.sync:
            return
        try:
            self.sync = Sync()
        except Exception as e:
            logger.exception(e)

    async def add_device(self, host, port, name=None):
        # TODO: This function does too much :)

        # Create a connection to the device
        async with asyncio.timeout(3):
            ctrl_transport_ = await TCPTransport.create(host, port, name=name)
            ctrl_protocol = await type(self).get_protocol_implementation().create(ctrl_transport_.get_remote_ip(), ctrl_transport_)
            await ctrl_protocol.start()

        # Get carrier the device controls. In the future, other device types may be added here.
        entity = await ctrl_protocol.get_entity()
        entity_id = entity.id
        # Save entity in self._raw_entity_dict to respond to incoming GetEntitiesRequests
        self._raw_entity_dict[entity_id] = entity
        # Parse entity to the internal python abstraction
        path = Path.parse(entity_id)

        device = Device.create_from_entity_type_tree(path ,entity)
        for carrier in device.carriers:
            self.computer.add_carrier(carrier)
            self.protocols[ctrl_protocol].add(carrier.path)
            self.devices[carrier.path] = DeviceEntry(carrier.path, ctrl_transport_.get_remote_ip(), ctrl_protocol)


        #cmd transport callbacks
        ctrl_protocol.register_callback(
            pb.MessageV1.RUN_STATE_CHANGE_MESSAGE_FIELD_NUMBER,
            self.handle_run_state_change,
            extra_args=[ctrl_protocol]
        )
        ctrl_protocol.register_callback(
            pb.MessageV1.ERROR_MESSAGE_FIELD_NUMBER,
            self.handle_error
        )

        #data transport callbacks
        ctrl_protocol.register_callback(
            pb.MessageV1.RUN_DATA_MESSAGE_FIELD_NUMBER,
            self.handle_run_data
        )

        ctrl_protocol.register_callback(
            pb.MessageV1.RUN_DATA_END_MESSAGE_FIELD_NUMBER,
            self.handle_run_data_end
        )

        ctrl_protocol.register_callback(
            pb.MessageV1.ERROR_MESSAGE_FIELD_NUMBER,
            self.handle_error
        )

        #self.computer.add_carrier(carrier)
        #self.devices[path] = DeviceEntry(path, ctrl_transport_.get_remote_ip(), ctrl_protocol)
        #self.protocols[ctrl_protocol].add(path)

        device_ip_mapping: dict[int, pb.Address] = {}
        for idx, device in enumerate(self.devices.values()):
            device_ip_mapping[idx] = pb.Address(data = device.get_remote_ip().packed)

        for device in self.devices.values():
            await device.protocol.register_external_entities(device_ip_mapping)

        await ctrl_protocol.udp_data_streaming(get_free_udp_port(6733))



    # ██   ██  █████  ███    ██ ██████  ██      ███████ ██████  ███████
    # ██   ██ ██   ██ ████   ██ ██   ██ ██      ██      ██   ██ ██
    # ███████ ███████ ██ ██  ██ ██   ██ ██      █████   ██████  ███████
    # ██   ██ ██   ██ ██  ██ ██ ██   ██ ██      ██      ██   ██      ██
    # ██   ██ ██   ██ ██   ████ ██████  ███████ ███████ ██   ██ ███████

    async def handle_run_state_change(self, msg: pb.RunStateChangeMessage, protocol: Protocol):
        """A handler for incoming :class:`.RunStateChangeMessage` messages."""
        logger.debug("Received run state change: %s.", repr(msg.new_))
        if distributed_run_state := self._ongoing_runs.get(UUID(msg.run.id), None):
            for path in self.protocols[protocol]:
                distributed_run_state.track(path, RunState.from_pb(msg.new_), msg.reason)
        else:
            logger.warning("Received run state change with unknown id %s.", msg.run.id)

    def decode_data(self, data_pb: pb.DaqData):
        data_type = data_pb.type
        dtype = None
        match data_type.WhichOneof("kind"):
            case "integer":
                bitwidth = data_type.integer.bitwidth
                if data_type.integer.signess == pb.IntegerType.Signedness.Signed:
                    dtype = np.dtype(f'int{bitwidth}')
                else:
                    dtype = np.dtype(f'uint{bitwidth}')
            case "float_":
                bitwidth = data_type.float_.bitwidth
                dtype = np.dtype(f'float{bitwidth}')
            case _:
                return np.array([], dtype=dtype)

        data = np.frombuffer(data_pb.data, dtype=dtype)
        return (data * data_pb.gain) + data_pb.offset

    async def handle_run_data(self, msg: pb.RunDataMessage):
        """A handler for incoming :class:`.RunDataMessage` messages."""
        if run := self.runs.get(UUID(msg.run.id), None):
            pb_data = msg.data

            chunk = msg.run.chunk

            data = self.decode_data(pb_data)
            data = data.reshape(msg.alignment, msg.sample_count, order='F')
            data = data[0:msg.channel_count, :]

            path = Path(msg.entity.path.split('/'))
            for block_idx, values in enumerate(data):
                channel = path.join(f"ADC{block_idx}")
                run.data[channel].extend(values)
        else:
            logger.warning("Received run data with unknown id %s.", msg.id)

    async def handle_error(self, msg: pb.ErrorMessage):
        logger.error( msg.description )

    async def handle_run_data_end(self, msg: pb.RunDataEndMessage):
        """A handler for incoming :class:`.RunDataEndMessage` messages."""
        if run := self.runs.get(UUID(msg.run.id), None):

            data = self.decode_data(msg.data)
            if data is None:
                return
            path = Path(msg.entity.path.split("/"))

            # For RunState.OP_END, all math block output signals are sampled and sent
            for block_idx in range(0, 6):
                block_path = path.join(f"{block_idx//2}").join(f"M{block_idx%2}")
                for output_idx in range(0, 8):
                    run.final_values[block_path.join(str(output_idx))] = data[block_idx * 8 + output_idx]
        else:
            logger.warning("Received run data with unknown id %s.", msg.id)

    #  ██████  ██████  ███    ███ ███    ███  █████  ███    ██ ██████  ███████
    # ██      ██    ██ ████  ████ ████  ████ ██   ██ ████   ██ ██   ██ ██
    # ██      ██    ██ ██ ████ ██ ██ ████ ██ ███████ ██ ██  ██ ██   ██ ███████
    # ██      ██    ██ ██  ██  ██ ██  ██  ██ ██   ██ ██  ██ ██ ██   ██      ██
    #  ██████  ██████  ██      ██ ██      ██ ██   ██ ██   ████ ██████  ███████

    @staticmethod
    def _forward_to(targets, fn, *args, **kwargs):
        forwards = (fn.__get__(target, target.__class__)(*args, **kwargs) for target in targets)
        return asyncio.gather(*forwards)

    def forward_set_config(self, message: pb.ConfigCommand):
        # TODO: Think about whether this is actually the correct approach.
        #       Possibly, one should introduce a new MultiProtocol and move the forwarding there.
        # TODO: This should not be here at least, but live in the Proxy

        # prepare a message with no configs that we can fill later
        empty_message = pb.ConfigCommand()
        empty_message.CopyFrom(message)
        while len(empty_message.bundle.configs) > 0:
            empty_message.bundle.configs.pop()

        forwards = set()
        for protocol, managed_paths in self.protocols.items():
            partial_request = pb.ConfigCommand()
            partial_request.CopyFrom(empty_message)

            for path in managed_paths:
                to_delete = []
                for config in message.bundle.configs:
                    if config.entity.path.startswith(path):
                        to_delete.append(config)
                        partial_request.bundle.configs.append(config)

                # remove items from original message
                for config in to_delete:
                    message.bundle.configs.remove(config)

            if len(partial_request.bundle.configs) > 0:
                forwards.add(
                    protocol.send_body_and_wait_response(partial_request)
                )

        # Check if there are remaining configurations
        if message.bundle.configs:
            keys = [c.entity.path for c in message.bundle.configs]
            raise UnknownEntityTypeError(
                "Could not forward configuration to unknown entities %s.", keys
            )
        return asyncio.gather(*forwards)

    async def hack(self, cmd: str, data: typing.Any) -> typing.Any:
        """
        Send the passed data as a 'hack' request, only used during development.
        It allows to pass and receive arbitrary data to and from the hybrid controller.
        """
        return await self.protocol.hack_request(cmd, data)

    async def get_status(self, entity, recursive):
        device = self.devices[entity.path.to_root()]
        return await device.protocol.get_status(recursive=recursive)

    async def get_system_temperatures(self):
        # TODO: Don't access self.devices.values() and self.devices.keys() separately
        responses = await self._forward_to([entry.protocol for entry in self.devices.values()], Protocol.get_system_temperatures)
        measurements = [
            measurement
            for dataset in responses
            for measurement in dataset.measurements
        ]
        return pb.TemperatureDataset(measurements=measurements)

    async def get_computer(self) -> REDAC:
        """
        Retrieve the current hardware configuration of the REDAC.
        """
        entities = await self.protocol.get_entity()
        computer = REDAC.create_from_entity_type_tree(entities)
        return computer

    async def set_computer(self, computer: REDAC):
        """
        Change the configuration of all carrier boards and sub-entities on the REDAC.

        :param computer: The :class:`.REDAC` object containing the configuration to be set.
        :return: None
        """

        # TODO: Add proper comparison/hash functions and use sets
        carriers_left = list(computer.carriers)
        for protocol, managed_paths in self.protocols.items():
            carriers_here = list()
            for carrier in carriers_left:
                if carrier.path in managed_paths:
                    carriers_here.append(carrier)
            for carrier in carriers_here:
                carriers_left.remove(carrier)

            await protocol.set_configs(carriers_here)

    async def start_run(
        self, run: typing.Optional[Run] = None, entities: typing.Optional[typing.Iterable[Path]] = None
    ) -> DistributedRunState:
        """
        Start a run (computation) and return a :class:`.DistributedRunState` object tracking its progress.

        The start of a computation is synchronized across all involved mREDACs. The actual start is
        triggered globally via the SYNC signal connected to all mREDACs. But before that, one needs
        to ensure that all mREDACs are already listening to the SYNC signal. The necessary steps
        depend on the deployment type of the analog computer and whether calibration is enabled.

        In standalone mode, an arbitrarily chosen mREDAC sends out the SYNC signal immediately after
        it reaches TAKE_OFF state. Thus, it needs to be ensured that all other mREDACs are ready
        to receive it before that happens (i.e. they need to reach TAKE_OFF before). It is not possible
        to send StartRunRequests to all but the first mREDAC and then send the "master" StartRunRequest after,
        since all mREDACs need to enter the calibration process as part of preparing a run. Additionally,
        some information necessary for the calibration is tied to the run (e.g. the partitioning).
        Luckily, the calibration process already implicitly synchronizes all mREDACs. So the firmware simply
        makes the chosen mREDAC wait a small amount of time after calibration is done, to ensure that it
        reaches TAKE_OFF after all other mREDACs and can safely send out the SYNC signal.

        In SC (proxy) mode, all mREDACs wait for an incoming SYNC signal after they have reached TAKE_OFF.
        Once that is confirmed, the super-controller can generate the SYNC signal (see Proxy class).
        This function does not take care of that.

        :param run: The :class:`.Run` to be started, including its configuration. If None, a new run is created.
        :param entities: Optional list of entities to include in the run.
        :param timeout: Optional timeout.
        :return: A :class:`DistributedRunState` that tracks the run's state.
        """
        if run is None:
            run_class = self.get_run_implementation()
            run = run_class()
        self.runs[run.id_] = run
        self._ongoing_runs[run.id_] = run_state = DistributedRunState(run)
        logger.info("Starting run %s.", repr(run))

        # Set SYNC id
        run.sync.group = run.partition.id

        # Determine involved protocols based on the selected entities
        if not entities:
            entities = set(self.devices.keys())
        involved_protocols = {
            protocol for protocol, managed_devices in self.protocols.items() if managed_devices.intersection(entities)
        }
        if not involved_protocols:
            raise ValueError("No protocols are involved in the selected entities for the run.")

        # In standalone mode, we tell the first mREDAC to generate the SYNC signal
        first_protocol, first_paths = next(iter(self.protocols.items()))
        path_for_sync_mredac = next(iter(first_paths))

        if run.calibration.enabled and run.calibration.leader is None:
            run.calibration = replace(run.calibration, leader=path_for_sync_mredac)

        if self.standalone:
            if not run.calibration.enabled:
                raise NotImplementedError("Standalone mode requires calibration for implicit synchronisation.")

            run.sync = replace(run.sync, enabled=True, master=path_for_sync_mredac)


        # Send StartRunRequests to all mREDAC, possibly adapting run.sync_config
        # We always tell the first device it should lead the calibration process
        start_run_requests = []
        for protocol in involved_protocols:
            run_state.add_paths(*self.protocols[protocol])
            start_run_requests.append(
                Protocol.start_run_request.__get__(protocol, protocol.__class__)(
                    id_=run.id_,
                    run_config=run.config,
                    daq_config=run.daq,
                    sync_config=run.sync,
                    calibration_config=run.calibration,
                    partition_config=run.partition,
                )
            )
        await asyncio.gather(*start_run_requests)

        return run_state

    async def start_and_await_run(self, run: typing.Optional[Run] = None, timeout=100) -> Run:
        """
        A convenience function which starts a run, blocks until it is completed and returns it.

        :param run: The :class:`.Run` to be started, including its configuration. If None, a new run is created.
        :param timeout: Timeout
        :return: The completed :class:`.Run`.
        """
        # Queue the run on the computer and wait until all involved entities are ready for take-off.
        try:
            run_state = await asyncio.wait_for(self.start_run(run), timeout=timeout)
        except asyncio.TimeoutError as exc:
            if exc.args:
                raise
            else:
                raise asyncio.TimeoutError("Timeout while queueing run.") from exc
        async with asyncio.timeout(timeout):
            await run_state.wait_all(RunState.DONE)
        del self._ongoing_runs[run.id_]
        # Return run
        return run

    async def get_config(self, entity: Entity, *, recursive: bool = True):
        device = self.devices[entity.path.to_root()]
        return await device.protocol.get_config(entity.path, recursive=recursive)

    async def set_config(self, entity: Entity):
        """
        Change the configuration of a singe entity.

        :param entity: The entity to change.
        :return: None
        """
        device = self.devices[entity.path.to_root()]
        await device.protocol.set_config(entity)

    async def reset(self, keep_calibration: bool = True, sync: bool = True):
        """
        Reset the hybrid controller and the analog computer to its initial configuration.

        :param keep_calibration: Whether to keep the calibration.
        :param sync: Whether to write the reset values to the hardware.
        :return: None
        """
        # TODO: Actually reset self.computer as well
        return await self._forward_to(self.protocols, Protocol.reset, keep_calibration=keep_calibration, sync=sync)

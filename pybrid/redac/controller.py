# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import asyncio
import logging
import typing
from collections import defaultdict
from copy import deepcopy
from dataclasses import replace
from uuid import UUID

from pybrid.base.transport import TCPTransport
from .carrier import Carrier
from .computer import REDAC
from .entities import Entity, Path, UnknownEntityTypeError
from .protocol.messages import RunStateChangeMessage, RunDataMessage, SetCircuitRequest
from .protocol.protocol import Protocol
from .run import Run, RunState, RunError
from .sync import Sync, SyncMode

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

    def get_invovlved_paths(self) -> typing.Iterable[Path]:
        return self._states.keys()

    def track(self, path: Path, state: RunState, reason: str | None = None):
        self._states[path][state].set()
        if state == RunState.ERROR and not self._any_error_future.done():
            self._any_error_future.set_exception(RunError(f"Error on entity {path}: {reason or "Unknown Error"}"))

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
    devices: dict[Path, Protocol]
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

    async def __aenter__(self):
        # Devices are already started in add_device
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        for device in self.devices.values():
            await device.stop()

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
            transport_ = await TCPTransport.create(host, port, name=name)
            protocol = await Protocol.create(transport_)
        await protocol.start()
        # Get carrier the device controls. In the future, other device types may be added here.
        entities = await protocol.get_entities()
        assert len(entities) >= 1
        for entity_id, sub_entities in entities.items():
            # Save entity in self._raw_entity_dict to respond to incoming GetEntitiesRequests
            self._raw_entity_dict[entity_id] = deepcopy(sub_entities)
            # Parse entity to the internal python abstraction
            path = Path.parse(entity_id)
            carrier = Carrier.create_from_entity_type_tree(path, sub_entities)
            protocol.register_callback(RunStateChangeMessage, self.handle_run_state_change, extra_args=[protocol])
            protocol.register_callback(RunDataMessage, self.handle_run_data, extra_args=[path])
            self.computer.add_carrier(carrier)
            self.devices[path] = protocol
            self.protocols[protocol].add(path)

    # ██   ██  █████  ███    ██ ██████  ██      ███████ ██████  ███████
    # ██   ██ ██   ██ ████   ██ ██   ██ ██      ██      ██   ██ ██
    # ███████ ███████ ██ ██  ██ ██   ██ ██      █████   ██████  ███████
    # ██   ██ ██   ██ ██  ██ ██ ██   ██ ██      ██      ██   ██      ██
    # ██   ██ ██   ██ ██   ████ ██████  ███████ ███████ ██   ██ ███████

    async def handle_run_state_change(self, msg: RunStateChangeMessage, protocol: Protocol):
        """A handler for incoming :class:`.RunStateChangeMessage` messages."""
        logger.debug("Received run state change: %s.", msg)
        if distributed_run_state := self._ongoing_runs.get(msg.id, None):
            for path in self.protocols[protocol]:
                distributed_run_state.track(path, msg.new, msg.reason)
        else:
            logger.warning("Received run state change with unknown id %s.", msg.id)

    async def handle_run_data(self, msg: RunDataMessage, path: Path):
        """A handler for incoming :class:`.RunDataMessage` messages."""
        if run := self.runs.get(msg.id, None):
            if msg.state == RunState.OP:
                # For RunState.OP, data is sent only for channels explicitly requested
                for data_pkg in msg.data:
                    for block_idx, data_point in enumerate(data_pkg):
                        # TODO: This is pretty inefficient
                        channel = Path(msg.entity).join(f"ADC{block_idx}")
                        run.data[channel].append(data_point)
            elif msg.state == RunState.OP_END:
                # For RunState.OP_END, all math block output signals are sampled and sent
                for block_idx, data in enumerate(msg.data):
                    block_path = Path(msg.entity).join(f"{block_idx//2}").join(f"M{block_idx%2}")
                    for output_idx, value in enumerate(data):
                        run.final_values[block_path.join(str(output_idx))] = value
            else:
                logger.warning("Received run data with unexpected state %s.", msg.state)
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

    def forward_set_circuit(self, message: SetCircuitRequest):
        # TODO: Think about whether this is actually the correct approach.
        #       Possibly, one should introduce a new MultiProtocol and move the forwarding there.
        # TODO: This should not be here at least, but live in the Proxy
        forwards = set()
        for protocol, managed_paths in self.protocols.items():
            partial_config = {}
            target_entity = Path()
            for path in managed_paths:
                if config := message.config.pop(path.id_, None):
                    if len(managed_paths) > 1:
                        partial_config[path.id_] = config
                    else:
                        partial_config = config
                        target_entity = path
            if partial_config:
                forwards.add(
                    protocol.send_message_and_wait_response(
                        SetCircuitRequest(entity=target_entity, config=partial_config)
                    )
                )
        # Check if there are remaining configurations
        if message.config:
            raise UnknownEntityTypeError(
                "Could not forward configuration to unknown entities %s.", message.config.keys()
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
        return await device.get_status(recursive=recursive)

    async def get_system_temperatures(self):
        # TODO: Don't access self.devices.values() and self.devices.keys() separately
        result = {}
        responses = await self._forward_to(self.devices.values(), Protocol.get_system_temperatures)
        for path, response in zip(self.devices.keys(), responses):
            result[path] = response
        return result

    async def get_computer(self) -> REDAC:
        """
        Retrieve the current hardware configuration of the REDAC.
        """
        entities = await self.protocol.get_entities()
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
        protocol_for_sync_mredac = None
        if self.standalone:
            protocol_for_sync_mredac = next(iter(involved_protocols))
            if not run.config.calibrate:
                raise NotImplementedError("Standalone mode requires calibration for implicit synchronisation.")
            if len(self.protocols[protocol_for_sync_mredac]) > 1:
                raise NotImplementedError("Standalone mode does not yet support non-direct connections to mREDACs.")

        # Send StartRunRequests to all mREDAC, possibly adapting run.sync_config
        start_run_requests = []
        for protocol in involved_protocols:
            run_state.add_paths(*self.protocols[protocol])
            start_run_requests.append(
                Protocol.start_run_request.__get__(protocol, protocol.__class__)(
                    id_=run.id_,
                    config=run.config,
                    daq_config=run.daq,
                    sync_config=run.sync if protocol is not protocol_for_sync_mredac else replace(run.sync, mode=SyncMode.MASTER),
                    partition_config=run.partition,
                )
            )
        await asyncio.gather(*start_run_requests)

        return run_state

    async def start_and_await_run(self, run: typing.Optional[Run] = None, timeout=6) -> Run:
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
        return await device.get_config(entity.path, recursive=recursive)

    async def set_config(self, entity: Entity):
        """
        Change the configuration of a singe entity.

        :param entity: The entity to change.
        :return: None
        """
        device = self.devices[entity.path.to_root()]
        await device.set_config(entity)

    async def reset(self, keep_calibration: bool = True, sync: bool = True):
        """
        Reset the hybrid controller and the analog computer to its initial configuration.

        :param keep_calibration: Whether to keep the calibration.
        :param sync: Whether to write the reset values to the hardware.
        :return: None
        """
        # TODO: Actually reset self.computer as well
        return await self._forward_to(self.protocols, Protocol.reset, keep_calibration=keep_calibration, sync=sync)

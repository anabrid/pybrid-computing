# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import asyncio
import logging
import typing
from collections import defaultdict
from copy import deepcopy
from uuid import UUID

from pybrid.base.transport import TCPTransport
from .carrier import Carrier
from .computer import REDAC
from .entities import Entity, Path, UnknownEntityTypeError
from .protocol.messages import RunStateChangeMessage, RunDataMessage, SetCircuitRequest
from .protocol.protocol import Protocol
from .run import Run, RunState
from .sync import Sync

logger = logging.getLogger(__name__)


class DistributedRunState:
    #: A dictionary tracking each possible RunState for each involved carrier
    _states: dict[Path, dict[RunState, asyncio.Semaphore]]
    #: The run which state we are tracking
    run: Run
    #: The run once it's done
    run_future: asyncio.Future

    def __init__(self, run, paths: typing.Iterable[Path]):
        self._states = {path: {state: asyncio.Semaphore(0) for state in RunState} for path in paths}
        self.run = run
        self.run_future = asyncio.Future()

    def get_invovlved_paths(self) -> typing.Iterable[Path]:
        return self._states.keys()

    def track(self, path: Path, state: RunState):
        self._states[path][state].release()

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
        await asyncio.gather(*[entity[state].acquire() for entity in self._states.values()])


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

    def __init__(self):
        self.computer = REDAC(entities=[])
        self.devices = dict()
        self.protocols = defaultdict(set)
        self.runs = dict()
        self._raw_entity_dict = dict()
        self._ongoing_runs = dict()
        self.sync = None

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
                distributed_run_state.track(path, msg.new)
        else:
            logger.warning("Received run state change with unknown id %s.", msg.id)

    async def handle_run_data(self, msg: RunDataMessage, path: Path):
        """A handler for incoming :class:`.RunDataMessage` messages."""
        if run := self.runs.get(msg.id, None):
            for data_pkg in msg.data:
                for idx, data_point in enumerate(data_pkg):
                    # TODO: This is pretty inefficient
                    channel = Path(msg.entity).join(f"ADC{idx}")
                    run.data[channel].append(data_point)

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
        Start a run (computation) on the REDAC.

        :param run: The :class:`.Run` to be started, including its configuration. If None, a new run is created.
        :return: An :class:`asyncio.Future` which can be awaited and will return the run object once it is done.
        """
        if run is None:
            run_class = self.get_run_implementation()
            run = run_class()

        logger.info("Starting run %s with %s.", repr(run), run.partition)

        # Do preparations for runs that will actually be started
        self.runs[run.id_] = run
        run.sync.group = run.partition.id

        # Forward request to involved devices and track their individual state
        if not entities:
            entities = set(self.devices.keys())
        self._ongoing_runs[run.id_] = run_state = DistributedRunState(run, entities)
        involved_protocols = set()
        for protocol, managed_devices in self.protocols.items():
            if managed_devices.intersection(entities):
                involved_protocols.add(protocol)
        await self._forward_to(
            involved_protocols,
            Protocol.start_run_request,
            id_=run.id_,
            config=run.config,
            daq_config=run.daq,
            sync_config=run.sync,
            partition_config=run.partition,
        )
        return run_state

    async def start_and_await_run(self, run: typing.Optional[Run] = None, timeout=5) -> Run:
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
            raise asyncio.TimeoutError("Timeout while queueing run.") from exc
        try:
            await asyncio.wait_for(run_state.wait_all(RunState.DONE), timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise asyncio.TimeoutError("Timeout while waiting for all carriers to reach RunState.DONE.") from exc
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

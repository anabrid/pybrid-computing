# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import asyncio
import logging
import typing
from asyncio import Future
from uuid import UUID

from pybrid.base.hybrid.utils import build_entity_path_dict
from pybrid.base.transport import TCPTransport
from .carrier import Carrier
from .computer import REDAC
from .entities import Entity, Path
from .protocol.messages import RunStateChangeMessage, RunDataMessage
from .protocol.protocol import Protocol
from .run import Run, RunState

logger = logging.getLogger(__name__)


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
    devices: dict[Path, Protocol]
    #: List of all runs started by this controller.
    runs: dict[UUID, Run] = dict()
    _ongoing_runs: dict[UUID, dict[Protocol, asyncio.Future]] = dict()

    def __init__(self):
        self.computer = REDAC(entities=[])
        self.devices = dict()

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

    async def add_device(self, host, port):
        # Create a connection to the device
        async with asyncio.timeout(3):
            transport_ = await TCPTransport.create(host, port)
            protocol = await Protocol.create(transport_)
        protocol.register_callback(RunStateChangeMessage, self.handle_run_state_change)
        protocol.register_callback(RunDataMessage, self.handle_run_data)
        await protocol.start()
        # Get carrier the device controls. In the future, other device types may be added here.
        entities = await protocol.get_entities()
        assert len(entities) == 1
        for entity_id, sub_entities in entities.items():
            path = Path.parse(entity_id)
            carrier = Carrier.create_from_entity_type_tree(path, sub_entities)
            self.computer.carriers.append(carrier)
            self.computer._entities_by_path.update(build_entity_path_dict([carrier]))
            self.devices[path] = protocol

    # ██   ██  █████  ███    ██ ██████  ██      ███████ ██████  ███████
    # ██   ██ ██   ██ ████   ██ ██   ██ ██      ██      ██   ██ ██
    # ███████ ███████ ██ ██  ██ ██   ██ ██      █████   ██████  ███████
    # ██   ██ ██   ██ ██  ██ ██ ██   ██ ██      ██      ██   ██      ██
    # ██   ██ ██   ██ ██   ████ ██████  ███████ ███████ ██   ██ ███████

    def handle_run_state_change(self, protocol: Protocol, msg: RunStateChangeMessage):
        """A handler for incoming :class:`.RunStateChangeMessage` messages."""
        logger.debug("Received run state change: %s.", msg)
        if run := self.runs.get(msg.id, None):
            run.state = RunState(msg.new)
            if run.state.is_done():
                self._ongoing_runs[run.id_][protocol].set_result(run.state)
        else:
            logger.warning("Received run state change with unknown id %s.", msg.id)

    def handle_run_data(self, protocol: Protocol, msg: RunDataMessage):
        """A handler for incoming :class:`.RunDataMessage` messages."""
        if run := self.runs.get(msg.id, None):
            adc_paths = [Path(msg.entity).join(f"ADC{idx}") for idx in range(run.daq.num_channels)]
            for data_pkg in msg.data:
                for channel, data_point in zip(adc_paths, data_pkg):
                    run.data[channel].append(data_point)

    #  ██████  ██████  ███    ███ ███    ███  █████  ███    ██ ██████  ███████
    # ██      ██    ██ ████  ████ ████  ████ ██   ██ ████   ██ ██   ██ ██
    # ██      ██    ██ ██ ████ ██ ██ ████ ██ ███████ ██ ██  ██ ██   ██ ███████
    # ██      ██    ██ ██  ██  ██ ██  ██  ██ ██   ██ ██  ██ ██ ██   ██      ██
    #  ██████  ██████  ██      ██ ██      ██ ██   ██ ██   ████ ██████  ███████

    @staticmethod
    async def _forward_to(targets, fn, *args, **kwargs):
        forwards = (fn.__get__(target, target.__class__)(*args, **kwargs) for target in targets)
        return await asyncio.gather(*forwards)

    async def hack(self, cmd: str, data: typing.Any) -> typing.Any:
        """
        Send the passed data as a 'hack' request, only used during development.
        It allows to pass and receive arbitrary data to and from the hybrid controller.
        """
        return await self.protocol.hack_request(cmd, data)

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
        for carrier in computer.carriers:
            await self.set_config(carrier)

    async def start_run(self, run: typing.Optional[Run] = None) -> Future:
        """
        Start a run (computation) on the REDAC.

        :param run: The :class:`.Run` to be started, including its configuration. If None, a new run is created.
        :return: An :class:`asyncio.Future` which can be awaited and will return the run object once it is done.
        """
        if run is None:
            run_class = self.get_run_implementation()
            run = run_class()
        self.runs[run.id_] = run
        # Create a future for each device we will forward this message to, so we can track which ones are finished.
        devices = self.devices.values()
        futures = {device: asyncio.get_event_loop().create_future() for device in devices}
        self._ongoing_runs[run.id_] = futures
        await self._forward_to(devices, Protocol.start_run_request, id_=run.id_, config=run.config, daq_config=run.daq)
        # Return a combined awaitable
        return asyncio.gather(*futures.values())

    async def start_and_await_run(self, run: typing.Optional[Run] = None, timeout=5) -> Run:
        """
        A convenience function which starts a run, blocks until it is completed and returns it.

        :param run: The :class:`.Run` to be started, including its configuration. If None, a new run is created.
        :param timeout: Timeout
        :return: The completed :class:`.Run`.
        """
        run_future = await self.start_run(run)

        final_run_states = await asyncio.wait_for(run_future, timeout=timeout)
        del self._ongoing_runs[run.id_]
        if any(state is RunState.ERROR for state in final_run_states):
            run.state = RunState.ERROR
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
        return await self._forward_to(
            self.devices.values(), Protocol.reset, keep_calibration=keep_calibration, sync=sync
        )

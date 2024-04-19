# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import asyncio
import logging
import typing
from asyncio import Future
from uuid import UUID

from pybrid.base.hybrid import BaseController

from .computer import REDAC
from .entities import Entity, Path
from .protocol.messages import RunStateChangeMessage, RunDataMessage
from .protocol.protocol import Protocol
from .run import Run, RunState

logger = logging.getLogger(__name__)


class Controller(BaseController):
    """
    Abstraction of the REDAC hybrid controller.

    The hybrid controller is an interface to all relevant functions to configure and control the REDAC.
    It also collects all :class:`Run` instances started with it.

    The controller object also holds references to the underlying protocol and transport objects and manages them.
    """
    computer: REDAC
    protocol: Protocol
    #: List of all runs started by this controller.
    runs: dict[UUID, Run] = dict()
    _ongoing_runs: dict[UUID, Future] = dict()

    @classmethod
    def get_run_implementation(cls) -> typing.Type[Run]:
        """Returns the specific :class:`.Run` implementation used by the REDAC."""
        return Run

    async def start(self) -> None:
        await super().start()
        self.protocol.register_callback(RunStateChangeMessage, self.handle_run_state_change)
        self.protocol.register_callback(RunDataMessage, self.handle_run_data)

    def handle_run_state_change(self, msg: RunStateChangeMessage):
        """A handler for incoming :class:`.RunStateChangeMessage` messages."""
        logger.debug("Received run state change: %s.", msg)
        if run := self.runs.get(msg.id, None):
            run.state = RunState(msg.new)
            if run.state.is_done():
                self._ongoing_runs.pop(run.id_).set_result(run)
        else:
            logger.warning("Received run state change with unknown id %s.", msg.id)

    def handle_run_data(self, msg: RunDataMessage):
        """A handler for incoming :class:`.RunDataMessage` messages."""
        if run := self.runs.get(msg.id, None):
            adc_paths = [Path(msg.entity).join(f"ADC{idx}") for idx in range(run.daq.num_channels)]
            for data_pkg in msg.data:
                for channel, data_point in zip(adc_paths, data_pkg):
                    run.data[channel].append(data_point)
            last_t = len(run.data["t"])
            run.data["t"].extend(range(last_t, last_t + len(msg.data)))

    #  ██████  ██████  ███    ███ ███    ███  █████  ███    ██ ██████  ███████
    # ██      ██    ██ ████  ████ ████  ████ ██   ██ ████   ██ ██   ██ ██
    # ██      ██    ██ ██ ████ ██ ██ ████ ██ ███████ ██ ██  ██ ██   ██ ███████
    # ██      ██    ██ ██  ██  ██ ██  ██  ██ ██   ██ ██  ██ ██ ██   ██      ██
    #  ██████  ██████  ██      ██ ██      ██ ██   ██ ██   ████ ██████  ███████

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
            run = await self.create_run()
        self.runs[run.id_] = run
        self._ongoing_runs[run.id_] = run_future = asyncio.get_event_loop().create_future()
        await self.protocol.start_run_request(run.id_, run.config, run.daq)
        return run_future

    async def start_and_await_run(self, run: typing.Optional[Run] = None, timeout=5) -> Run:
        """
        A convenience function which starts a run, blocks until it is completed and returns it.

        :param run: The :class:`.Run` to be started, including its configuration. If None, a new run is created.
        :param timeout: Timeout
        :return: The completed :class:`.Run`.
        """
        run_future = await self.start_run(run)
        await asyncio.wait_for(run_future, timeout=timeout)
        return run_future.result()

    async def set_config(self, entity: Entity):
        """
        Change the configuration of a singe entity.

        :param entity: The entity to change.
        :return: None
        """
        await self.protocol.set_config(entity)

    async def reset(self, keep_calibration: bool = True, sync: bool = True):
        """
        Reset the hybrid controller and the analog computer to its initial configuration.

        :param keep_calibration: Whether to keep the calibration.
        :param sync: Whether to write the reset values to the hardware.
        :return: None
        """
        await self.protocol.reset(keep_calibration=keep_calibration, sync=sync)

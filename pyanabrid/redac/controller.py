# Copyright (c) 2022 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
#
# This file is part of the pyanabrid software packet.
#
# ANABRID_BEGIN_LICENSE:GPL
# Commercial License Usage
# Licensees holding valid commercial anabrid licenses may use this file in
# accordance with the commercial license agreement provided with the
# Software or, alternatively, in accordance with the terms contained in
# a written agreement between you and Anabrid GmbH. For licensing terms
# and conditions see https://www.anabrid.com/licensing. For further
# information use the contact form at https://www.anabrid.com/contact.
#
# GNU General Public License Usage
# Alternatively, this file may be used under the terms of the GNU
# General Public License version 3 as published by the Free Software
# Foundation and appearing in the file LICENSE.GPL3 included in the
# packaging of this file. Please review the following information to
# ensure the GNU General Public License version 3 requirements
# will be met: https://www.gnu.org/licenses/gpl-3.0.html.
# For Germany, additional rules exist. Please consult /LICENSE.DE
# for further agreements.
# ANABRID_END_LICENSE

import asyncio
import logging
import typing
from asyncio import Future
from uuid import UUID

from pyanabrid.base.hybrid.controller import BaseController

from .computer import REDAC
from .entities import Entity
from .protocol.messages import RunStateChangeMessage
from .protocol.protocol import Protocol
from .run import Run, RunState

logger = logging.getLogger(__name__)


class Controller(BaseController):
    computer: REDAC
    protocol: Protocol
    runs: dict[UUID, Run] = dict()
    _ongoing_runs: dict[UUID, Future] = dict()

    @classmethod
    def get_run_implementation(cls) -> typing.Type[Run]:
        return Run

    async def start(self) -> None:
        await super().start()
        self.protocol.register_callback(RunStateChangeMessage, self.handle_run_state_change)

    def handle_run_state_change(self, msg: RunStateChangeMessage):
        logger.debug("Received run state change: %s.", msg)
        if run := self.runs.get(msg.id, None):
            run.state = RunState(msg.new)
            if run.state.is_done():
                self._ongoing_runs.pop(run.id_).set_result(run)
        else:
            logger.warning("Received run state change with unknown id %s.", msg.id)

    #  ██████  ██████  ███    ███ ███    ███  █████  ███    ██ ██████  ███████
    # ██      ██    ██ ████  ████ ████  ████ ██   ██ ████   ██ ██   ██ ██
    # ██      ██    ██ ██ ████ ██ ██ ████ ██ ███████ ██ ██  ██ ██   ██ ███████
    # ██      ██    ██ ██  ██  ██ ██  ██  ██ ██   ██ ██  ██ ██ ██   ██      ██
    #  ██████  ██████  ██      ██ ██      ██ ██   ██ ██   ████ ██████  ███████

    async def get_computer(self) -> REDAC:
        entities = await self.protocol.get_entities()
        computer = REDAC.create_from_entity_type_tree(entities)
        return computer

    async def set_computer(self, computer: REDAC):
        raise NotImplementedError

    async def start_run(self, run: typing.Optional[Run] = None) -> Future:
        if run is None:
            run = self.create_run()
        self.runs[run.id_] = run
        self._ongoing_runs[run.id_] = run_future = asyncio.get_event_loop().create_future()
        await self.protocol.start_run_request(run.id_, run.config)
        return run_future

    async def start_and_await_run(self, run: typing.Optional[Run] = None, timeout=5) -> Run:
        run_future = await self.start_run(run)
        await asyncio.wait_for(run_future, timeout=timeout)
        return run_future.result()

    async def set_config(self, entity: Entity):
        await self.protocol.set_config(entity)

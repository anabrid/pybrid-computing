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
import itertools
import typing

from pyanabrid.analog.base import AliasedModulesType, AliasedDict
from pyanabrid.analog.modelone.modules import Module, ModuleType, ModuleIdentifier
# TODO: This should be protocol-agnostic
from pyanabrid.hybrid.protocol.v1.messages import RunStateChangeMessage, RunDataMessage
# END TODO

from .base import BaseController
from .run import BaseRun, RunState


class RunIdPool:
    def __init__(self):
        self.range = range(1, 12345)
        self.iter = itertools.cycle(iter(self.range))

    def next(self):
        return next(self.iter)


_run_id_pool = RunIdPool()


class Run(BaseRun):
    run_id: int = Field(default_factory=lambda: _run_id_pool.next())


class AwaitableRun(Run):
    _done_future: asyncio.Future = PrivateAttr()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._done_future = asyncio.get_event_loop().create_future()


class ModelOneController(BaseController):
    runs: typing.Dict[int, AwaitableRun]

    def __init__(self, protocol, *args, **kwargs):
        super().__init__(protocol, *args, **kwargs)
        self.runs = dict()
        self.protocol.add_incoming_msg_handler(RunStateChangeMessage, self._run_state_change_msg_handler)
        self.protocol.add_incoming_msg_handler(RunDataMessage, self._run_data_msg_handler)

    def _run_state_change_msg_handler(self, msg: RunStateChangeMessage):
        run = self.runs[msg.run_id]
        run.state = RunState.from_v1_protocol(msg.new)
        print("Run ", run, " changed to state ", run.state)
        if run.state is RunState.DONE:
            run._done_future.set_result(run)

    def _run_data_msg_handler(self, msg: RunDataMessage):
        run = self.runs[msg.run_id]
        run.data[RunState.from_v1_protocol(msg.state)].extend(msg.data)

    async def new_run(self):
        new_run = AwaitableRun()
        self.runs.update({new_run.run_id: new_run})
        await self.start_run(new_run)
        return await self.runs[new_run.run_id]._done_future

    async def start_run(self, run) -> bool:
        response = await self.protocol.start_run(**run.dict())
        if not response.accepted:
            run.state = RunState.ERROR
            return False
        else:
            run.state = RunState.QUEUED
            return True

    async def get_modules(self) -> AliasedModulesType:
        response = await self.protocol.get_modules()

        def _convert_to_module(id_, module_data):
            module_type = ModuleType(module_data["type"])
            module_class = Module.get_module_class(module_type)
            return module_class.parse_obj({"module_id": id_})

        return AliasedDict({
            ModuleIdentifier(_id): _convert_to_module(ModuleIdentifier(_id), module_data)
            for _id, module_data in response.items()
        })

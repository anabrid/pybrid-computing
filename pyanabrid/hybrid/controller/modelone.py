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
from pydantic import BaseModel, Field, PrivateAttr

from pyanabrid.analog.base import AliasedModulesType, AliasedList, AnalogComputationElement
from pyanabrid.analog.modelone.modules import Module, ModuleType, ModuleIdentifier
# TODO: This should be protocol-agnostic
#       Not really. Model-1 controller will only ever talk via v1 Protocol
#       Though it would be nicer to have it somewhere else maybe :)
from pyanabrid.hybrid.protocol.v1.messages import (
    RunStateChangeMessage, RunDataMessage,
    SetConfigRequest, SetConfigResponse,
    SetDAQRequest, SetDAQResponse,
)

from .base import BaseController
from .run import BaseRun, RunState


class DAQChannel(BaseModel):
    element: AnalogComputationElement


class DAQConfiguration(BaseModel):
    channels: typing.List[DAQChannel] = list()

    def add_element(self, element: AnalogComputationElement):
        self.channels.append(DAQChannel(element=element))

    def to_request_payload(self):
        return [
            {"path": channel.element.path}
            for channel in self.channels
        ]


class RunIdPool:
    def __init__(self):
        self.range = range(1, 12345)
        self.iter = itertools.cycle(iter(self.range))

    def next(self):
        return next(self.iter)


_run_id_pool = RunIdPool()


class Run(BaseRun):
    run_id: int = Field(default_factory=lambda: _run_id_pool.next())
    daq_config: DAQConfiguration = DAQConfiguration()


class AwaitableRun(Run):
    # TODO: This should be a wrapper, not a subclass to preserve original run object (so people can compare, serach, ...)
    _done_future: asyncio.Future = PrivateAttr()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._done_future = asyncio.get_event_loop().create_future()

    @classmethod
    def from_run(cls, run: Run):
        return cls(**run.copy())


class ModelOneController(BaseController):
    runs: typing.Dict[int, Run]
    run_futures: typing.Dict[int, asyncio.Future]

    def __init__(self, protocol, *args, **kwargs):
        super().__init__(protocol, *args, **kwargs)
        self.runs = dict()
        self.run_futures = dict()
        self.protocol.add_incoming_msg_handler(RunStateChangeMessage, self._run_state_change_msg_handler)
        self.protocol.add_incoming_msg_handler(RunDataMessage, self._run_data_msg_handler)

        self._run_data_msg_last_state = None

    def _run_state_change_msg_handler(self, msg: RunStateChangeMessage):
        run = self.runs[msg.run_id]
        run.state = RunState.from_v1_protocol(msg.new)
        run.overload = msg.overload
        run.external_halt = msg.external_halt
        if run.state is RunState.DONE:
            self.run_futures[run.run_id].set_result(run)

    def _run_data_msg_handler(self, msg: RunDataMessage):
        run = self.runs[msg.run_id]
        if run.state != self._run_data_msg_last_state:
            self._run_data_msg_last_state = run.state
            channel_idx = 0
        else:
            channel_idx = run.total_data_samples_in_state(run.state) % len(run.daq_config.channels)

        for d in msg.data:
            run.data[run.daq_config.channels[channel_idx].element][run.state].append(d)
            channel_idx = (channel_idx + 1) % len(run.daq_config.channels)

    async def new_run(self, run=None):
        if run is None:
            run = Run()
        self.runs.update({run.run_id: run})
        self.run_futures.update({run.run_id: asyncio.get_running_loop().create_future()})
        await self.start_run(run)
        return await self.run_futures[run.run_id]

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
            module = module_class.parse_obj({"path": (id_, )})
            return module

        module_list = AliasedList(
            _convert_to_module(ModuleIdentifier(_id), module_data)
            for _id, module_data in response.items()
        )
        for idx, module in enumerate(module_list):
            module_list.add_alias(module.id_, idx)
        return module_list

    async def set_module_config(self, module_configs: typing.List[Module]) -> bool:
        for module in module_configs:
            if not module.elements:
                continue
            request: SetConfigRequest = SetConfigRequest.parse_obj({
                "module": module.path.root,
                **module.dict(exclude={'elements': {'__all__': {'element_id'}}})
            })
            response: SetConfigResponse = await self.protocol.send_message_and_wait_response(request)
            if not response.was_successful():
                raise RuntimeError("Error while configuring module.")
        # TODO: Handle response errors

    async def set_daq_config(self, daq_config: DAQConfiguration):
        request: SetDAQRequest = SetDAQRequest.parse_obj(
            daq_config.to_request_payload()
        )
        response: SetDAQResponse = await self.protocol.send_message_and_wait_response(request)
        if not response.was_successful():
            raise RuntimeError("Setting DAQ Configuration failed")
        return response.__root__

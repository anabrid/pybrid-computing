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

import typing
from abc import ABC, abstractmethod

from pyanabrid.base.hybrid.computer import AnalogComputer

from .protocol import BaseProtocol
from .run import BaseRun


class BaseController(ABC):
    computer: typing.Optional[AnalogComputer]
    protocol: BaseProtocol

    def __init__(self, protocol, *args, **kwargs):
        self.computer = None
        self.protocol = protocol
        self.initialize_protocol(self.protocol)

    @classmethod
    async def create(cls, protocol, *args, **kwargs) -> 'BaseController':
        controller = cls(protocol)
        return controller

    # Utilities

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()

    # Initializations

    async def start(self) -> None:
        await self.protocol.start()
        self.computer = await self.get_computer()

    async def stop(self) -> None:
        await self.protocol.stop()

    def initialize_protocol(self, protocol: BaseProtocol):
        pass

    # Implementations

    @classmethod
    @abstractmethod
    def get_run_implementation(cls) -> typing.Type[BaseRun]:
        ...

    async def create_run(self, **kwargs):
        run_class = self.get_run_implementation()
        return run_class(**kwargs)

    # Commands

    @abstractmethod
    async def get_computer(self) -> AnalogComputer:
        ...

    @abstractmethod
    async def set_computer(self, computer):
        pass

    @abstractmethod
    async def start_and_await_run(self, run=None):
        ...

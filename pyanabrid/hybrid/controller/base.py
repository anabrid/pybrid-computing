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

from abc import ABC, abstractmethod
import typing

from pyanabrid.analog.base import AliasedModulesType
from pyanabrid.hybrid.protocol import BaseProtocol
from pyanabrid.hybrid.protocol.v1 import Protocol as Protocol_v1

from .run import BaseRun


class BaseController(ABC):
    protocol: typing.Union[BaseProtocol, Protocol_v1]

    def __init__(self, protocol, *args, **kwargs):
        self.protocol = protocol

    @classmethod
    async def create(cls, protocol, *args, **kwargs):
        return cls(protocol)

    @abstractmethod
    async def new_run(self, *args, **kwargs) -> BaseRun:
        ...

    @abstractmethod
    async def start_run(self, *args, **kwargs):
        ...

    @abstractmethod
    async def get_modules(self) -> AliasedModulesType:
        ...

    @abstractmethod
    async def set_module_config(self, *args, **kwargs) -> bool:
        ...

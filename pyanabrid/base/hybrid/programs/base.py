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

import logging
import sys
import typing
from abc import ABC, abstractmethod

from ..computer import AnalogComputer
from ..controller import BaseController
from ..run import BaseRun

logger = logging.getLogger(__name__)


class BaseProgram(ABC):
    controller: BaseController
    run: BaseRun
    computer: typing.Optional[AnalogComputer]
    output: typing.Optional[typing.IO]
    logger: logging.Logger

    def __init__(self, controller: BaseController, run: BaseRun, output: typing.Optional[typing.IO] = None):
        self.controller = controller
        self.run = run
        self.output = output or sys.stdout
        self.logger = logger

    def print(self, *args, **kwargs):
        kwargs["file"] = self.output
        print(*args, **kwargs)

    async def entrypoint(self):
        # If BaseProgram is started via command line, computer is already synchronized
        if self.controller.computer is None:
            await self.controller.get_computer()
        self.computer = self.controller.computer
        return await self.start()

    @abstractmethod
    async def start(self):
        ...

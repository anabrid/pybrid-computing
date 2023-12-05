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

from .base import BaseProgram
from ..computer import AnalogComputer
from ..run import BaseRun


class SimpleRun(BaseProgram):
    run: typing.Optional[BaseRun]

    async def start(self):
        self.set_configuration(self.run, self.computer)
        await self.controller.set_computer(self.computer)
        self.run = await self.controller.start_and_await_run(self.run)
        self.run_done(self.run)

    # Methods to overwrite

    def create_run(self, computer):
        return self.run

    def set_configuration(self, run: BaseRun, computer: AnalogComputer):
        raise NotImplementedError("You must supply a 'set_configuration' function in your sub-class.")

    def run_done(self, run):
        self.print("Successfully completed %s." % run)


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
import typing

from pyanabrid.analog.base import AliasedModulesType

from .base import BaseController
from .modelone import ModelOneController, Run, DAQConfiguration, DAQChannel


logger = logging.getLogger(__name__)


class RunEvaluateReconfigureLoop:
    controller: ModelOneController
    output: typing.Optional[typing.IO]
    logger: logging.Logger
    daq_config: DAQConfiguration

    runs: typing.List[Run]
    modules: typing.Optional[AliasedModulesType]

    # TODO: These should maybe be None and not change the machine default
    CTRL_PERIOD: typing.ClassVar[typing.Optional[int]] = 500
    IC_TIME: typing.ClassVar[typing.Optional[int]] = 5_000
    OP_TIME: typing.ClassVar[typing.Optional[int]] = 25_000
    HALT_ON_OVERLOAD: typing.ClassVar[bool] = False
    HALT_ON_EXTERNAL_TRIGGER: typing.ClassVar[bool] = False

    def __init__(self, controller: BaseController, output: typing.Optional[typing.IO] = None):
        self.controller = controller
        self.output = output
        self.logger = logger

        self.runs = list()
        self.modules = None

        self.daq_config = DAQConfiguration()

    async def start(self):
        # First, get the modules from the controller and allow the user to set aliases
        self.modules = await self.controller.get_modules()
        self.modules = self.set_aliases(self.modules) or self.modules
        # Set initial configuration
        self.set_configuration(self.modules, [])
        await self.controller.set_module_config(self.modules)
        await self.controller.set_daq_config(self.daq_config)

        # Then loop until user decides to stop
        while True:
            new_run = self.create_run()
            finished_run = await self.controller.new_run(new_run)
            self.runs.append(finished_run)
            if not self.run_done(finished_run):
                break
            self.set_configuration(self.modules, self.runs)
            await self.controller.set_module_config(self.modules)
        self.loop_done(self.runs)

    # Convenience functions
    # These may be overwritten by the user, but less likely

    def create_run(self):
        return Run(ctrl_period=self.CTRL_PERIOD, ic_time=self.IC_TIME, op_time=self.OP_TIME,
                   daq_config=self.daq_config,
                   halt_on_overload=self.HALT_ON_OVERLOAD, halt_on_external_trigger=self.HALT_ON_EXTERNAL_TRIGGER)

    # User functions
    # These should be overwritten by the user

    def set_aliases(self, modules: AliasedModulesType) -> typing.Optional[AliasedModulesType]:
        return modules

    def set_configuration(self, modules: AliasedModulesType, previous_runs: typing.List[Run]):
        return dict()

    def run_done(self, run: Run) -> bool:
        return False

    def loop_done(self, runs: typing.List[Run]):
        pass

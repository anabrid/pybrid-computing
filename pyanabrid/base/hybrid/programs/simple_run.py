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
    """
    SimpleRun Abstraction

    This class implements a user-extendable version of a single analog computation.
    Users should inherit this class and overwrite the following function to inject their specific code.

    * :func:`~pyanabrid.base.hybrid.programs.SimpleRun.set_configuration`
      for configuring the run
    * :func:`~pyanabrid.base.hybrid.programs.SimpleRun.run_done`
      for evaluating a completed run
    """

    run: typing.Optional[BaseRun]

    async def start(self):
        """
        Pre-implemented specialization of :func:`BaseProgram.start`.

        When the :class:`SimpleRun` user program is used,
        this function calls the user-supplied :func:`set_configuration` function,
        then applies the configuration to the analog computer, starts a computation
        and then calls the user-supplied :func:`run_done` function.
        """
        self.set_configuration(self.run, self.computer)
        await self.controller.set_computer(self.computer)
        self.run = await self.controller.start_and_await_run(self.run)
        self.run_done(self.run)

    # Methods to overwrite

    def create_run(self, computer):
        return self.run

    def set_configuration(self, run: BaseRun, computer: AnalogComputer):
        """
        User-supplied function to set the configuration of the analog computer before the run is started.

        To configure the analog computer, change any configuration parameter of the ``computer`` argument
        or any of its sub-entities (clusters, blocks and functions).
        See :doc:`/redac/configurations` for all possible configurations.

        The configuration is automatically applied by the underlying program logic.
        """
        raise NotImplementedError("You must supply a 'set_configuration' function in your sub-class.")

    def run_done(self, run):
        """
        User-supplied function to consume the result of a run.

        Refer to the analog computer specific run class implementation for all available information.
        Use ``run.data`` to access the data captured during computation.
        """
        self.print("Successfully completed %s." % run)


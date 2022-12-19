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

r"""
Run-Evaluate-Reconfigure-Loop
=============================

A typical hybrid computing process involves an iteration between digital and analog computations:
An initial configuration is applied to the analog computer and the analog computation is started.
The user waits for the result and evaluates or collects the data from the analog computation.
He then defines a new analog configuration for the next run and repeats the process as long as necessary.

For example parameter variation problems or iterative analog algorithms can be implemented in such a manner.
Since most of the necessary logic is very generic, the :code:`pyanabrid` package provides an abstraction
that takes care of most of the underlying work: The :code:`RunEvaluateReconfigureLoop` class.

The :code:`RunEvaluateReconfigureLoop` implements all necessary parts of the following process flow.
First the class is initialized and the user can provide additional code that is executed once in the beginning,
e.g. to initialize variables used later.
Then a user-supplied :code:`set config` function defines a configuration for the analog computer,
which is then applied by the generic process logic.
A run with this config is automatically started and the program waits until it is complete.
The result is collected from the analog computer and passed to a user-supplied :code:`evaluate` function.
Depending on its return value, the loop restarts from the beginning or ends.

Example
-------

The following example calculates an exponential decay :math:`y(t) = \exp(-\beta * t)`
for different values of :math:`\beta`.

.. code-block:: python

    import matplotlib.pyplot as plt

    from pyanabrid.analog.base.elements import Potentiometer, Integrator
    from pyanabrid.hybrid.controller.recl import RunEvaluateReconfigureLoop
    from pyanabrid.hybrid.controller.run import RunState


    class UserProgram(RunEvaluateReconfigureLoop):
        IC_TIME = 5_000
        OP_TIME = 50_000

        y: Integrator
        beta: Potentiometer

        def init_loop(self, modules):
            self.y = modules["0x0160"].elements[0]
            self.beta = modules["0x0080"].elements[0]
            self.beta.factor = 0

            self.daq_config.add_element(self.y)

        def next_configuration(self, modules, previous_runs):
            self.beta.factor += 0.1

        def run_done(self, run):
            data = run.data[self.y][RunState.OP]

            plt.plot(data)
            plt.ylabel("y")
            plt.show()

            return len(self.runs) < 10

        def loop_done(self, runs):
            print("Finished RECLoop with", len(runs), "runs")

You can execute this :code:`UserProgram` with the :code:`anabrid` command line tool.

.. code-block:: bash

    anabrid hybrid control [...] recl path/to/user/program/file.py


Class Documentation
-------------------

"""

import logging
import typing

from pyanabrid.base.hybrid.computer import AnalogComputer
from pyanabrid.base.hybrid.run import BaseRun, BaseRunConfig

from .base import BaseProgram

logger = logging.getLogger(__name__)


class RunEvaluateReconfigureLoop(BaseProgram):
    """
    Run-Evaluate-Reconfigure-Loop Abstraction

    This class implements the typical process flow of a run-evaluate-reconfigure-loop.
    Users should inherit this class and overwrite the following function to inject their specific code.

    * :func:`~pyanabrid.hybrid.controller.recl.RunEvaluateReconfigureLoop.init_loop` for one-time initialization code
    * :func:`~pyanabrid.hybrid.controller.recl.RunEvaluateReconfigureLoop.next_configuration` for configuring the next run
    * :func:`~pyanabrid.hybrid.controller.recl.RunEvaluateReconfigureLoop.run_done` for evaluating a completed run
    * :func:`~pyanabrid.hybrid.controller.recl.RunEvaluateReconfigureLoop.loop_done` for final evaluation or cleanup code
    """

    runs: typing.List[BaseRun]

    RUN_CONFIG: BaseRunConfig = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.runs = list()

    async def start(self):
        """
        Entrypoint for starting the Run-Evaluate-Reconfigure-Loop

        This function is called automatically by the anabrid command line tool.
        You should *not* need to call it unless you manually start a loop.

        :return: None
        """
        # self.computer is initialized by BaseProgram.entrypoint

        # First, allow the user to initialize whatever they want.
        self.init_loop(self.computer)

        # Set initial configuration
        self.next_configuration(self.computer, [])
        await self.controller.set_computer(self.computer)

        # Then loop until user decides to stop
        while True:
            new_run = self.create_run()
            finished_run = await self.controller.start_and_await_run(new_run)
            self.runs.append(finished_run)
            if not self.run_done(finished_run):
                break
            self.next_configuration(self.computer, self.runs)
            await self.controller.set_computer(self.computer)
        self.loop_done(self.runs)

    # Convenience functions
    # These may be overwritten by the user, but less likely

    def get_run_kwargs(self):
        kwargs = {}
        if self.RUN_CONFIG is not None:
            kwargs["config"] = self.RUN_CONFIG
        return kwargs

    def create_run(self):
        run_class = self.controller.get_run_implementation()
        run = run_class(**self.get_run_kwargs())
        return run

    # User functions
    # These should be overwritten by the user

    def init_loop(self, computer: AnalogComputer):
        """
        User-supplied function called before the loop is started.

        Use this function to set user variables and constant computer configuration values.
        Acquire any necessary resources (like opening files).

        :param computer: A representation of the specific analog computer
        :return: None
        """
        return None

    def next_configuration(self, computer: AnalogComputer, previous_runs: typing.List[BaseRun]):
        """
        User-supplied function called before each run.

        Use this function to set the configurations for the upcoming run.
        You can either modify the passed modules or access modules you 'remembered' in init_loop.

        This function is also called for the first run, with previous_runs being an empty list.

        :param computer: A representation of the specific analog computer
        :param previous_runs: List of previous runs
        :return: None
        """
        return computer

    def run_done(self, run: BaseRun) -> bool:
        """
        User-supplied function called after a run is completed.

        Use this function to evaluate the results of the latest run.
        If the loop should be stopped after this run, return True.

        :param run: The just completed run
        :return: True if loop should be stopped, False to continue
        """
        return False

    def loop_done(self, runs: typing.List[BaseRun]):
        """
        User-supplied function called after the loop exits.

        Use this to close any open resources (like files) and to do evaluation across multiple runs.

        :param runs: List of all executed runs.
        :return: None
        """
        pass

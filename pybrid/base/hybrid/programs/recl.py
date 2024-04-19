# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

r"""
Run-Evaluate-Reconfigure-Loop
=============================

A typical hybrid computing process involves an iteration between digital and analog computations:
An initial configuration is applied to the analog computer and the analog computation is started.
The user waits for the result and evaluates or collects the data from the analog computation.
He then defines a new analog configuration for the next run and repeats the process as long as necessary.

For example parameter variation problems or iterative analog algorithms can be implemented in such a manner.
Since most of the necessary logic is very generic, the :code:`pybrid` package provides an abstraction
that takes care of most of the underlying work: The :code:`RunEvaluateReconfigureLoop` class.

The :code:`RunEvaluateReconfigureLoop` implements all necessary parts of the following process flow.
First the class is initialized and the user can provide additional code that is executed once in the beginning,
e.g. to initialize variables used later.
Then a user-supplied :code:`set config` function defines a configuration for the analog computer,
which is then applied by the generic process logic.
A run with this config is automatically started and the program waits until it is complete.
The result is collected from the analog computer and passed to a user-supplied :code:`evaluate` function.
Depending on its return value, the loop restarts from the beginning or ends.

You can execute a :code:`UserProgram` with the :code:`pybrid` command line tool.

.. code-block:: bash

    pybrid [...] recl path/to/user/program/file.py


Class Documentation
-------------------

"""

import logging
import typing

from pybrid.base.hybrid.computer import AnalogComputer
from pybrid.base.hybrid.run import BaseRun

from .base import BaseProgram

logger = logging.getLogger(__name__)


class RunEvaluateReconfigureLoop(BaseProgram):
    """
    Run-Evaluate-Reconfigure-Loop Abstraction

    This class implements the typical process flow of a run-evaluate-reconfigure-loop.
    Users should inherit this class and overwrite the following function to inject their specific code.

    * :func:`~pybrid.base.hybrid.programs.recl.RunEvaluateReconfigureLoop.set_user_variables`
      for one-time initialization code
    * :func:`~pybrid.base.hybrid.programs.recl.RunEvaluateReconfigureLoop.initial_configuration`
      for configuring the first run
    * :func:`~pybrid.base.hybrid.programs.recl.RunEvaluateReconfigureLoop.next_configuration`
      for configuring the next run (except the first)
    * :func:`~pybrid.base.hybrid.programs.recl.RunEvaluateReconfigureLoop.run_done`
      for evaluating a completed run
    * :func:`~pybrid.base.hybrid.programs.recl.RunEvaluateReconfigureLoop.loop_done`
      for final evaluation or cleanup code
    """

    runs: typing.List[BaseRun]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.runs = list()

    async def start(self):
        """
        Entrypoint for starting the Run-Evaluate-Reconfigure-Loop

        This function is called automatically by the pybrid command line tool.
        You should *not* need to call it unless you manually start a loop.

        :return: None
        """
        # self.computer is initialized by BaseProgram.entrypoint

        # First, allow the user to initialize whatever they want.
        self.set_user_variables(self.computer)

        # Then loop until user decides to stop
        while True:
            new_run = self.create_run()
            # Set configuration
            if not self.runs:
                self.initial_configuration(new_run, self.computer)
            else:
                self.next_configuration(new_run, self.computer, self.runs)
            await self.controller.set_computer(self.computer)

            # Run
            finished_run = await self.controller.start_and_await_run(new_run)
            self.runs.append(finished_run)
            if not self.run_done(finished_run):
                break
        self.loop_done(self.runs)

    # Convenience functions
    # These may be overwritten by the user, but less likely

    def create_run(self):
        run_class = self.controller.get_run_implementation()
        # Possibly persist some configuration from previous runs or class attributes
        previous_run = self.runs[-1] if self.runs else None
        overwrites = self.get_run_kwargs()
        run = run_class.make_from_other_run(previous_run, **overwrites)
        return run

    # User functions
    # These should be overwritten by the user

    def set_user_variables(self, computer: AnalogComputer):
        """
        User-supplied function called before the loop is started.

        Use this function to set user variables and constant computer configuration values.
        Acquire any necessary resources (like opening files).

        :param computer: A representation of the specific analog computer
        :return: None
        """
        return None

    def initial_configuration(self, run: BaseRun, computer: AnalogComputer):
        """
        User-supplied function called before the first run.

        Use this function to set the configurations for the first run.
        Run configuration parameters (e.g. OP time or DAQ config) will be kept to future runs.

        :param run: First run that is about to be started
        :param computer: A representation of the specific analog computer
        :return: None
        """
        raise NotImplementedError("You need to implement the 'initial_configuration' function.")

    def next_configuration(self, run: BaseRun, computer: AnalogComputer, previous_runs: typing.List[BaseRun]):
        """
        User-supplied function called before each run except the first.

        Use this function to set the configurations for the upcoming run.
        You can either modify the passed modules or access modules you 'remembered' in init_loop.

        :param run: Run that is about to be started
        :param computer: A representation of the specific analog computer
        :param previous_runs: List of previous runs
        :return: None
        """
        raise NotImplementedError("You need to implement the 'next_configuration' function.")

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

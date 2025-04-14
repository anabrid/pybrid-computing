# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import logging
import sys
import typing
from abc import ABC, abstractmethod
from dataclasses import replace

from ..computer import AnalogComputer
from ..controller import BaseController
from ..run import BaseRun, BaseRunConfig, BaseDAQConfig

logger = logging.getLogger(__name__)


class BaseProgram(ABC):
    """
    Base class for user programs.
    """

    #: Shortcut to set :attr:`.BaseRun.config` if not None.
    RUN_CONFIG: BaseRunConfig = None
    #: Shortcut to set :attr:`.BaseRun.daq_config` if not None.
    DAQ_CONFIG: BaseDAQConfig = None

    #: Underlying controller used by this program.
    controller: BaseController
    #: Initial or current run.
    run: BaseRun
    #: Underlying computer abstraction.
    computer: typing.Optional[AnalogComputer]
    #: Output stream to write data to. Used to redirect to file or similar.
    output: typing.Optional[typing.IO]
    #: Logger instance.
    logger: logging.Logger

    #: Whether to ignore errors during a run by default
    ignore_errors: typing.ClassVar[bool] = False
    ignore_config_errors: typing.ClassVar[bool] = False
    ignore_run_errors: typing.ClassVar[bool] = False

    def __init__(
        self,
        controller: BaseController,
        run: BaseRun,
        output: typing.Optional[typing.IO] = None,
    ):
        self.controller = controller
        self.run = run
        self.output = output or sys.stdout
        self.logger = logger

    def print(self, *args, **kwargs):
        """Convenience wrapper around :code:`print()` which redirects it to :attr:`output`."""
        kwargs["file"] = self.output
        print(*args, **kwargs)

    async def entrypoint(self):
        """
        Entrypoint of all user programs.

        This is either called automatically by the :code:`user-program` command of the command line,
        or needs to be called when initialising a user program by hand.
        """
        # If BaseProgram is started via command line, computer is already synchronized
        if self.controller.computer is None:
            await self.controller.get_computer()
        self.computer = self.controller.computer
        # Creating a run is async, thus it can not happen in __init__
        # If BaseProgram is started via command line, run is already set, and we need to overwrite it partly.
        if self.run is None:
            run_class = self.controller.get_run_implementation()
            self.run = run_class(**self.get_run_kwargs())
        else:
            self.run = replace(self.run, **self.get_run_kwargs())
        return await self.start()

    @abstractmethod
    async def start(self):
        """
        Abstract start method called by :func:`entrypoint`, to be overwritten.
        """
        ...

    def get_run_kwargs(self) -> dict:
        """
        Collects shortcut :attr:`RUN_CONFIG` and :attr:`DAQ_CONFIG` used when creating new runs.
        """
        kwargs = {}

        # Use *_CONFIG class variable if available
        if self.RUN_CONFIG is not None:
            kwargs["config"] = self.RUN_CONFIG
        if self.DAQ_CONFIG is not None:
            kwargs["daq"] = self.DAQ_CONFIG

        return kwargs

    def on_error(self, error: Exception):
        """
        Error handling function.

        Is called on any exception that can reasonably be handled by an average user.
        """
        if not self.ignore_errors:
            raise

    def on_run_error(self, run: BaseRun, error: Exception):
        """
        Error handling function.

        Is called on any exception raised during a computation.
        """
        if not self.ignore_run_errors:
            self.on_error(error)

    def on_config_error(self, run: BaseRun, error: Exception):
        """
        Error handling function.

        Is called on any exception raised during configuration.
        """
        if not self.ignore_run_errors:
            self.on_error(error)


class SingleRun(BaseProgram):
    """
    SimpleRun Abstraction

    This class implements a user-extendable version of a single analog computation.
    Users should inherit this class and overwrite the following function to inject their specific code.

    * :func:`~pybrid.base.hybrid.programs.SimpleRun.set_configuration`
      for configuring the run
    * :func:`~pybrid.base.hybrid.programs.SimpleRun.run_done`
      for evaluating a completed run
    """

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
        try:
            self.run = await self.controller.start_and_await_run(self.run)
        except Exception as exc:
            self.on_run_error(self.run, exc)
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


class MultipleRuns(BaseProgram):
    runs: list[BaseRun]

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
        # First, allow the user to initialize whatever they want.
        self.set_user_variables(self.computer)

        # Then loop until user decides to stop
        while True:
            new_run = self.create_run(self.run)
            # Set configuration
            if not self.runs:
                self._initial_configuration(new_run, self.computer)
            else:
                self._next_configuration(new_run, self.computer, self.runs)
            try:
                await self.controller.set_computer(self.computer)
            except Exception as exc:
                self.on_config_error(new_run, exc)

            # Run
            try:
                finished_run = await self.controller.start_and_await_run(new_run)
            except Exception as exc:
                self.on_run_error(new_run, exc)
            else:
                self.runs.append(finished_run)
                if not self._run_done(finished_run):
                    break
        self.loop_done(self.runs)

    def create_run(self, previous_run=None):
        run_class = self.controller.get_run_implementation()
        # Possibly persist some configuration from previous runs or class attributes
        overwrites = self.get_run_kwargs()
        run = run_class.make_from_other_run(previous_run, **overwrites)
        return run

    # Internal forwards to user-supplied functions

    def _initial_configuration(self, run: BaseRun, computer: AnalogComputer):
        return self.initial_configuration(run, computer)

    def _next_configuration(
        self,
        run: BaseRun,
        computer: AnalogComputer,
        previous_runs: typing.List[BaseRun],
    ):
        return self.next_configuration(run, computer, previous_runs)

    def _run_done(self, run: BaseRun) -> bool:
        return self.run_done(run)

    # Convenience functions
    # These may be overwritten by the user, but less likely

    def set_user_variables(self, computer: AnalogComputer):
        """
        User-supplied function called before the loop is started.

        Use this function to set user variables and constant computer configuration values.
        Acquire any necessary resources (like opening files).

        :param computer: A representation of the specific analog computer
        :return: None
        """
        return None

    # User functions
    # These should be overwritten by the user

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

    def next_configuration(
        self,
        run: BaseRun,
        computer: AnalogComputer,
        previous_runs: typing.List[BaseRun],
    ):
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
        :return: False if loop should be stopped, True to continue
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

# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import logging
import sys
import typing
from abc import ABC, abstractmethod
from dataclasses import replace

from pybrid.base.hybrid.computer import AnalogComputer
from pybrid.base.hybrid.controller import BaseController
from pybrid.base.hybrid.run import BaseRun, BaseRunConfig, BaseDAQConfig

logger = logging.getLogger(__name__)


class BaseProgram(ABC):
    RUN_CONFIG: BaseRunConfig = None
    DAQ_CONFIG: BaseDAQConfig = None

    controller: BaseController
    run: BaseRun
    computer: typing.Optional[AnalogComputer]
    output: typing.Optional[typing.IO]
    logger: logging.Logger

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
        """Redirect :func:`print` to :attr:`output`."""
        kwargs["file"] = self.output
        print(*args, **kwargs)

    async def entrypoint(self):
        """Entrypoint for all user programs.

        Called automatically by the ``user-program`` CLI command or manually
        when initialising a user program by hand.
        """
        if self.controller.computer is None:
            await self.controller.get_computer()
        self.computer = self.controller.computer
        if self.run is None:
            run_class = self.controller.get_run_implementation()
            self.run = run_class(**self.get_run_kwargs())
        else:
            self.run = replace(self.run, **self.get_run_kwargs())
        return await self.start()

    @abstractmethod
    async def start(self):
        ...

    def get_run_kwargs(self) -> dict:
        """Collect :attr:`RUN_CONFIG` and :attr:`DAQ_CONFIG` for run construction."""
        kwargs = {}
        if self.RUN_CONFIG is not None:
            kwargs["config"] = self.RUN_CONFIG
        if self.DAQ_CONFIG is not None:
            kwargs["daq"] = self.DAQ_CONFIG
        return kwargs

    def on_error(self, error: Exception):
        """Default error handler — re-raises unless :attr:`ignore_errors` is set."""
        if not self.ignore_errors:
            raise

    def on_run_error(self, run: BaseRun, error: Exception):
        """Called on any exception raised during a computation."""
        if not self.ignore_run_errors:
            self.on_error(error)

    def on_config_error(self, run: BaseRun, error: Exception):
        """Called on any exception raised during configuration."""
        if not self.ignore_run_errors:
            self.on_error(error)


class SingleRun(BaseProgram):
    """User-extendable single analog computation.

    Override :meth:`set_configuration` to configure the run and
    :meth:`run_done` to evaluate the completed result.
    """

    async def start(self):
        self.set_configuration(self.run, self.computer)
        session = self.controller.create_session()
        session.set_config(self.computer)
        session.run(self.run.config, daq=self.run.daq)
        try:
            results = await session.execute()
            if results:
                self.run = results[0]
        except Exception as exc:
            self.on_run_error(self.run, exc)
        self.run_done(self.run)

    def create_run(self, computer):
        return self.run

    def set_configuration(self, run: BaseRun, computer: AnalogComputer):
        """User-supplied: configure the analog computer before the run starts.

        Modify *computer* or its sub-entities (clusters, blocks, functions).
        The configuration is applied automatically by the program logic.
        """
        raise NotImplementedError("You must supply a 'set_configuration' function in your sub-class.")

    def run_done(self, run):
        """User-supplied: consume the result of a run.

        Use ``run.data`` to access captured data.
        """
        self.print("Successfully completed %s." % run)


class MultipleRuns(BaseProgram):
    runs: list[BaseRun]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.runs = list()

    async def start(self):
        """Run-Evaluate-Reconfigure loop until :meth:`run_done` returns False."""
        self.set_user_variables(self.computer)

        while True:
            new_run = self.create_run(self.run)
            if not self.runs:
                self._initial_configuration(new_run, self.computer)
            else:
                self._next_configuration(new_run, self.computer, self.runs)

            # Combined config + run in a single session to avoid rapid
            # session cycling that can crash the proxy.
            session = self.controller.create_session()
            session.set_config(self.computer)
            session.run(new_run.config, daq=new_run.daq)
            try:
                results = await session.execute()
            except Exception as exc:
                self.on_run_error(new_run, exc)
            else:
                finished_run = results[0] if results else new_run
                self.runs.append(finished_run)
                if not self._run_done(finished_run):
                    break
        self.loop_done(self.runs)

    def create_run(self, previous_run=None):
        run_class = self.controller.get_run_implementation()
        overwrites = self.get_run_kwargs()
        run = run_class.make_from_other_run(previous_run, **overwrites)
        return run

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

    def set_user_variables(self, computer: AnalogComputer):
        """User-supplied: called before the loop starts.

        Set user variables and constant computer configuration values.
        Acquire any necessary resources (like opening files).
        """
        return None

    def initial_configuration(self, run: BaseRun, computer: AnalogComputer):
        """User-supplied: configure the first run.

        Run configuration parameters (e.g. OP time, DAQ config) are carried
        forward to subsequent runs.
        """
        raise NotImplementedError("You need to implement the 'initial_configuration' function.")

    def next_configuration(
        self,
        run: BaseRun,
        computer: AnalogComputer,
        previous_runs: typing.List[BaseRun],
    ):
        """User-supplied: configure each run after the first.

        Modify *computer* or *run* based on *previous_runs*.
        """
        raise NotImplementedError("You need to implement the 'next_configuration' function.")

    def run_done(self, run: BaseRun) -> bool:
        """User-supplied: called after each run.

        Return False to stop the loop, True to continue.
        """
        return False

    def loop_done(self, runs: typing.List[BaseRun]):
        """User-supplied: called after the loop exits.

        Close open resources and evaluate results across all runs.
        """
        pass

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

    def __init__(self, controller: BaseController, run: BaseRun, output: typing.Optional[typing.IO] = None):
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
            self.run = await self.controller.create_run(**self.get_run_kwargs())
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

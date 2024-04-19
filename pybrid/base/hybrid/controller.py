# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import typing
from abc import ABC, abstractmethod

from pybrid.base.hybrid.computer import AnalogComputer

from .protocol import BaseProtocol
from .run import BaseRun


class BaseController(ABC):
    #: The computer controlled by this controller.
    computer: typing.Optional[AnalogComputer]
    #: The protocol used by this controller.
    protocol: BaseProtocol

    def __init__(self, protocol, *args, **kwargs):
        self.computer = None
        self.protocol = protocol
        self.initialize_protocol(self.protocol)

    @classmethod
    async def create(cls, protocol: BaseProtocol, *args, **kwargs) -> 'BaseController':
        """Create a new controller using the passed protocol."""
        controller = cls(protocol)
        return controller

    # Utilities

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()

    # Initializations

    async def start(self) -> None:
        """Initialize the controller, start protocol communication and
        request list of available entities from the analog computer."""
        await self.protocol.start()
        self.computer = await self.get_computer()

    async def stop(self) -> None:
        """De-initialize the controller and stop protocol communication."""
        await self.protocol.stop()

    def initialize_protocol(self, protocol: BaseProtocol):
        pass

    # Implementations

    @classmethod
    @abstractmethod
    def get_run_implementation(cls) -> typing.Type[BaseRun]:
        """Returns the specific :class:`BaseRun` implementation used by the analog computer."""
        ...

    async def create_run(self, **kwargs) -> BaseRun:
        """Create a run. All keyword arguments are passed to the underlying :class:`BaseRun` class."""
        run_class = self.get_run_implementation()
        return run_class(**kwargs)

    # Commands

    @abstractmethod
    async def get_computer(self) -> AnalogComputer:
        ...

    @abstractmethod
    async def set_computer(self, computer):
        pass

    @abstractmethod
    async def start_and_await_run(self, run=None):
        ...

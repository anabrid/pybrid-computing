# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

from __future__ import annotations

import asyncio
import typing
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, List, Optional

import pybrid.base.proto.main_pb2 as pb
from pybrid.base.hybrid.computer import AnalogComputer
from pybrid.base.hybrid.run import BaseDAQConfig, BaseRun, BaseRunConfig

if TYPE_CHECKING:
    # Deferred to avoid circular imports at module load time.
    # The cycle is:
    #   pybrid.redac.entities → pybrid.base.hybrid → base.hybrid.controller
    #   → pybrid.redac.connection (and pybrid.redac.sync)
    #   → pybrid.redac.entities  (partially initialised)
    from pybrid.redac.connection import ConnectionManager
    from pybrid.redac.session import Session


class BaseController(ABC):
    """Abstract base class for all hybrid analog computer controllers.

    Provides connection management, run tracking, sample listener registration,
    sync implementation selection, and lifecycle management.
    """

    computer: typing.Optional[AnalogComputer]
    connection_manager: "ConnectionManager"
    runs: dict
    sample_listeners: list
    _default_session: typing.Any
    _session_lock: asyncio.Lock

    def __init__(self) -> None:
        # Lazy imports to break circular dependency:
        # pybrid.redac.entities → pybrid.base.hybrid → controller
        # → pybrid.redac.connection/sync → pybrid.redac.entities (circular)
        from pybrid.redac.connection import ConnectionManager

        self.computer = None
        self.connection_manager = ConnectionManager()
        self.runs = {}
        self.sample_listeners = []
        self._default_session = None
        self._session_lock = asyncio.Lock()

    async def add_device(self, host: str, port: int, specification: Optional[pb.Module] = None) -> None:
        """Add device(s) from a network endpoint.

        Delegates discovery and connection management to :attr:`connection_manager`.
        Subclasses should override this method and call ``super().add_device()``
        to update :attr:`computer` with newly discovered carriers.
        """
        await self.connection_manager.add_device(host, port, specification)

    async def extract(self) -> pb.Module:
        """Return cached hardware specification from connection establishment."""
        return self.connection_manager.cache_descriptions

    def register_listener(self, listener) -> None:
        self.sample_listeners.append(listener)

    def unregister_listener(self, listener) -> None:
        """:raises ValueError: If the listener is not registered."""
        self.sample_listeners.remove(listener)

    def create_session(self) -> "Session":
        """Create a new Session bound to this controller."""
        from pybrid.redac.session import Session

        return Session(self)

    async def set_computer(self, computer) -> None:
        """.. deprecated:: Override in subclasses where the full implementation lives."""
        pass

    async def start_and_await_run(self, run=None, timeout: int = 100):
        """.. deprecated:: Use ``session.run(config).execute()`` instead."""
        raise NotImplementedError(
            "start_and_await_run() is deprecated. " "Override in the concrete controller subclass for now."
        )

    async def start(self) -> None:
        """No-op.  Channels are started during :meth:`add_device`."""

    async def stop(self) -> None:
        """Close all device connections."""
        await self.connection_manager.close_all()

    async def __aenter__(self) -> "BaseController":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.connection_manager.close_all()

    @classmethod
    @abstractmethod
    def get_run_implementation(cls) -> typing.Type[BaseRun]: ...

    @classmethod
    @abstractmethod
    def get_computer_type(cls) -> typing.Type[AnalogComputer]: ...

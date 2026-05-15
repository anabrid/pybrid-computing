# Copyright (c) 2022-2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""Base class for DummyDAC command handlers."""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pybrid.mock.connection import ClientConnection
    from pybrid.mock.dummy_dac import DummyDAC


class BaseHandler(ABC):
    """
    Base class for DummyDAC command handlers.

    Each handler is responsible for processing a specific command type
    and returning the appropriate response. Handlers have access to
    the DummyDAC server instance for state access and modification.

    :param server: The DummyDAC server instance.
    """

    def __init__(self, server: "DummyDAC"):
        """
        Initialize the handler with a reference to the server.

        :param server: The DummyDAC server instance.
        """
        self._server = server

    @property
    def server(self) -> "DummyDAC":
        """
        Access the DummyDAC server instance.

        :return: The DummyDAC server instance.
        """
        return self._server

    @abstractmethod
    async def handle(self, cmd: Any, connection: "ClientConnection") -> Any:
        """
        Handle the command and return a response.

        :param cmd: The protobuf command message.
        :param connection: The client connection instance.
        :return: The protobuf response message.
        """
        pass

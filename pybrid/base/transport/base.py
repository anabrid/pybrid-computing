# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

from abc import ABCMeta, abstractmethod
from asyncio import StreamReader, StreamWriter, wait_for

import logging


logger = logging.getLogger(__name__)


class BaseTransport(metaclass=ABCMeta):
    """
    Abstract base class for transports.

    Transports are based on :class:`asyncio.StreamReader` and :class:`asyncio.StreamWriter` objects.
    """

    def __init__(self, reader: StreamReader, writer: StreamWriter, name: str = None):
        self.reader = reader
        self.writer = writer
        self.name = name

    @classmethod
    @abstractmethod
    async def create(cls, *args, **kwargs):
        ...

    async def send_line(self, data: bytes) -> None:
        """Send one line of data over the transport. Newline character '\n' is appended automatically."""
        logger.debug("%s sending: %s + b'\\n'", self, data)
        self.writer.writelines([data, b"\n"])
        return await self.writer.drain()

    async def receive_line(self, timeout=1) -> bytes:
        """Receive one line of data from the transport."""
        data = await wait_for(self.reader.readline(), timeout=timeout)
        logger.debug("%s received: %s", self, data)
        # StreamReader.readline() may not necessarily return a whole line, see documentation
        if not data or data[-1] != 10:
            raise RuntimeError
        else:
            return data

    def close(self):
        """Close the underlying :class:`asyncio.StreamWriter`."""
        self.writer.close()

    def __repr__(self):
        return self.name or super().__repr__()

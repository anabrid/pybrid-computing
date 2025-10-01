# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

from abc import ABCMeta, abstractmethod
from asyncio import StreamReader, StreamWriter, wait_for, BaseTransport

import logging

from google.protobuf.json_format import MessageToJson

import pybrid.base.proto.main_pb2 as pb

from google.protobuf.internal import encoder
from google.protobuf.internal import decoder

logger = logging.getLogger(__name__)

encoder = encoder._VarintEncoder()

class StreamTransport(BaseTransport):
    """
    Abstract base class for transports.

    Transports are based on :class:`asyncio.StreamReader` and :class:`asyncio.StreamWriter` objects.
    """

    def __init__(self, reader: StreamReader, writer: StreamWriter, name: str = None):
        super().__init__()
        self.reader = reader
        self.writer = writer
        self.name = name

    @classmethod
    @abstractmethod
    async def create(cls, *args, **kwargs): ...

    async def send_packet(self, data: bytes) -> None:
        """Send one line of data over the transport. Newline character '\n' is appended automatically."""
        encoder(self.writer.write, len(data))
        self.writer.write(data)
        return await self.writer.drain()

    async def receive_varint(self, timeout=3) -> int | None:
        """Receive the length of the next message."""
        shift = 0
        result = 0
        while True:
            b = await wait_for(self.reader.read(1), timeout=timeout)
            if b == b"":
                raise EOFError("Unexpected EOF while reading varint")
            i = b[0]
            result |= (i & 0x7f) << shift
            if not (i & 0x80):
                break
            shift += 7

        return result

    async def receive_packet(self, timeout=3) -> bytes | None:
        """Receive one line of data from the transport."""

        msg_len = await self.receive_varint()
        if msg_len is None:
            return None

        data = await wait_for(self.reader.readexactly(msg_len), timeout=timeout)
        assert len(data) == msg_len

        if data:
            return data
        else:
            raise ConnectionError("Connection was probably closed.")

    def close(self):
        """Close the underlying :class:`asyncio.StreamWriter`."""
        self.writer.close()

    def __repr__(self):
        return self.name or super().__repr__()

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

class StreamTransport(BaseTransport):
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
    async def create(cls, *args, **kwargs): ...

    async def send_packet(self, data: bytes) -> None:
        """Send one line of data over the transport. Newline character '\n' is appended automatically."""
        self.writer.write(encoder._VarintBytes(len(data)))
        self.writer.write(data)
        return await self.writer.drain()

    async def receive_varint(self, timeout=3) -> int | None:
        """Receive the length of the next message."""
        varint_buffer = bytes()
        while True:
            new_byte = await wait_for(self.reader.read(1), timeout=timeout)
            if len(new_byte) == 0:
                return None
            varint_buffer += new_byte
            if varint_buffer[-1] & 0x80 == 0:
                break

        msg_len, bytes_read = decoder._DecodeVarint32(varint_buffer, 0)
        return msg_len

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

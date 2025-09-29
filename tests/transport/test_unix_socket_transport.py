# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import asyncio
from asyncio import StreamReader, StreamWriter

import pytest
import tempfile

from pybrid.base.transport import UnixSocketTransport


@pytest.fixture
def temp_filename():
    return tempfile.mktemp()


@pytest.fixture
async def unix_socket_server(temp_filename):

    async def handle_echo(reader: StreamReader, writer: StreamWriter):
        data = await reader.readline()
        message = data.decode()
        addr = writer.get_extra_info('peername')

        print(f"Received {message!r} from {addr!r}")

        print(f"Send: {message!r}")
        writer.write(data)
        await writer.drain()

        print("Close the connection")
        writer.close()

    server = await asyncio.start_unix_server(handle_echo, temp_filename)
    async with server:
        await server.start_serving()
        yield server
    # server.close() & await server.closed() is done by async with


@pytest.fixture
async def unix_socket_transport(temp_filename):
    transport = await UnixSocketTransport.create(temp_filename)
    yield transport
    transport.writer.close()


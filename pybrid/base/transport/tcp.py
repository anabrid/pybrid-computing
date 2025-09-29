# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import asyncio

from .stream import StreamTransport
from ipaddress import IPv4Address


class TCPTransport(StreamTransport):
    """A TCP/IP transport implementation for network communication."""

    @classmethod
    async def create(cls, host, port, /, **kwargs):
        """
        Create a new :class:`TCPTransport` instance for communicating over network.

        :param host: Target hostname or IP address.
        :param port: Target network port.
        :param kwargs: Keyword arguments are passed on to :class:`.BaseTransport`.
        :return: A :class:`TCPTransport` instance.
        """
        name = kwargs.pop("name", None)
        reader, writer = await asyncio.open_connection(host, port, **kwargs)
        return cls(reader=reader, writer=writer, name=name, **kwargs)

    def get_remote_ip(self) -> IPv4Address:
        socket = self.writer.get_extra_info('socket')
        if socket is not None:
            remote_ip, remote_port = socket.getpeername()
            return IPv4Address(remote_ip)
        else:
            return IPv4Address("0.0.0.0")


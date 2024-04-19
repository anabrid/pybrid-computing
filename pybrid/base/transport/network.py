# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import asyncio

from .base import BaseTransport


class TCPTransport(BaseTransport):
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
        reader, writer = await asyncio.open_connection(host, port, **kwargs)
        return cls(reader=reader, writer=writer, **kwargs)

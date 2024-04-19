# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

from serial_asyncio import open_serial_connection

from .base import BaseTransport


class SerialTransport(BaseTransport):
    """
    A transport abstraction for serial connections.
    """
    @classmethod
    async def create(cls, device, baudrate, /, **kwargs):
        """
        Create a new :class:`SerialTransport` instance.

        :param device: The serial device's path.
        :param baudrate: The baudrate to use.
        :param kwargs: Keyword arguments are passed on to :class:`.BaseTransport`.
        :return: A :class:`SerialTransport` instance.
        """
        reader, writer = await open_serial_connection(url=device, baudrate=baudrate)
        return cls(reader=reader, writer=writer, **kwargs)

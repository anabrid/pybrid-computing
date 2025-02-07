# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import asyncio

from .base import BaseTransport


class PassthroughTransport(BaseTransport):
    """
    A utility passthrough transport for testing purposes.

    Use it to pass a reader and a writer from your code into anything that uses transports.
    """
    @classmethod
    async def create(cls, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, **kwargs) -> 'PassthroughTransport':
        """
        Create a new :class:`PassthroughTransport` instance.

        :param reader: A :class:`asyncio.StreamReader` instance.
        :param writer: A :class:`asyncio.StreamWriter` instance.
        :param kwargs: Keyword arguments are passed on to :class:`.BaseTransport`.
        :return: A :class:`PassthroughTransport` instance.
        """
        return cls(reader=reader, writer=writer, **kwargs)

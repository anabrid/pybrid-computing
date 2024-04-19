# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import asyncio
import os
import tempfile
import typing

from .base import BaseTransport


class UnixSocketTransport(BaseTransport):
    """
    Transport based on unix sockets, mostly for testing purposes.
    """
    @classmethod
    async def create(cls, path: typing.Union[str, os.PathLike, None], **kwargs) -> 'UnixSocketTransport':
        """
        Create a new :class:`UnixSocketTransport`.

        :param path: Path which should be used for the socket. A temporary file is created if None.
        :param kwargs: Keyword arguments are passed on to :class:`.BaseTransport`.
        :return: A :class:`.UnixSocketTransport` instance
        """
        if path is None:
            path = tempfile.mktemp()
        reader, writer = await asyncio.open_unix_connection(path)
        return cls(reader=reader, writer=writer, **kwargs)

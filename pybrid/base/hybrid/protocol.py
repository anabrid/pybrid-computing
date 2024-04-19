# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import typing
from abc import ABC, abstractmethod

from packaging.version import Version
from pybrid.base.transport import BaseTransport


class ProtocolError(Exception):
    pass


class MessageNotImplemented(ProtocolError, NotImplementedError):
    pass


class MalformedDataError(ProtocolError, ValueError):
    pass


class MalformedMessageError(MalformedDataError):
    pass


class UnknownMessageError(MalformedMessageError):
    pass


class UnsuccessfulRequestError(ProtocolError):
    pass


class BaseProtocol(ABC):
    transport: BaseTransport
    version: Version

    @classmethod
    async def create(
            cls, transport: BaseTransport, version_: typing.Union[Version, int, str] = None
    ) -> 'BaseProtocol':
        if version_ is None:
            version = Version("1.0")
        elif isinstance(version_, Version):
            # version passed is a Version object
            version = version_
        elif isinstance(version_, int):
            # version passed is major
            version = Version(str(version_))
        elif isinstance(version_, str):
            # version passed is a str
            version = Version(version_)
        else:
            raise TypeError("version parameter has wrong type")
        protocol = cls(version=version, transport=transport)
        return protocol

    def __init__(self, transport: BaseTransport, version: Version):
        self.transport = transport
        self.version = version

    @abstractmethod
    async def start(self):
        ...

    @abstractmethod
    async def stop(self):
        ...

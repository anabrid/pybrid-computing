# Copyright (c) 2022 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
#
# This file is part of the pyanabrid software packet.
#
# ANABRID_BEGIN_LICENSE:GPL
# Commercial License Usage
# Licensees holding valid commercial anabrid licenses may use this file in
# accordance with the commercial license agreement provided with the
# Software or, alternatively, in accordance with the terms contained in
# a written agreement between you and Anabrid GmbH. For licensing terms
# and conditions see https://www.anabrid.com/licensing. For further
# information use the contact form at https://www.anabrid.com/contact.
#
# GNU General Public License Usage
# Alternatively, this file may be used under the terms of the GNU
# General Public License version 3 as published by the Free Software
# Foundation and appearing in the file LICENSE.GPL3 included in the
# packaging of this file. Please review the following information to
# ensure the GNU General Public License version 3 requirements
# will be met: https://www.gnu.org/licenses/gpl-3.0.html.
# For Germany, additional rules exist. Please consult /LICENSE.DE
# for further agreements.
# ANABRID_END_LICENSE

import typing
from abc import ABC, abstractmethod

from packaging.version import Version
from pyanabrid.base.transport import BaseTransport


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

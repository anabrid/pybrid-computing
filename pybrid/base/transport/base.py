# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

from abc import ABCMeta, abstractmethod
from asyncio import StreamReader, StreamWriter, wait_for

import logging
import pybrid.base.proto.main_pb2 as pb

from google.protobuf.internal import encoder
from google.protobuf.internal import decoder

logger = logging.getLogger(__name__)

class BaseTransport(metaclass=ABCMeta):
    """
    Abstract base class for transports.

    Transports are based on :class:`asyncio.StreamReader` and :class:`asyncio.StreamWriter` objects.
    """

    async def send_packet(self, data: bytes) -> None: ...

    async def receive_packet(self, timeout=3) -> bytes: ...

    def close(self): ...

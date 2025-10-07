# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import logging
from abc import ABCMeta, abstractmethod
from ipaddress import IPv4Address

logger = logging.getLogger(__name__)

class BaseTransport(metaclass=ABCMeta):
    """
    Abstract base class for transports.

    Transports are based on :class:`asyncio.StreamReader` and :class:`asyncio.StreamWriter` objects.
    """

    async def send_packet(self, data: bytes) -> None: ...

    async def receive_packet(self, timeout=3) -> bytes: ...

    def get_remote_ip(self) -> IPv4Address:
        return IPv4Address("0.0.0.0")

    def get_name(self) -> str:
        return ""

    def close(self): ...

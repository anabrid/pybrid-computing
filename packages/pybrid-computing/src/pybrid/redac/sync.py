# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import logging
import typing
from dataclasses import dataclass
from enum import Enum

from pyftdi.spi import SpiController

from pybrid.redac.entities import Path

logger = logging.getLogger(__name__)


class SyncMode(Enum):
    NONE = None
    STANDALONE = "standalone"
    SLAVE = "slave"
    MASTER = "master"

    def requires_external_sync(self):
        return self is SyncMode.STANDALONE


class SyncImplementationType(Enum):
    """System-level sync strategy.

    USBSPI: External USB FTDI SPI device triggers sync (Python Sync class).
    NATIVE: First mREDAC generates SYNC internally (master/slave config).
    """

    USBSPI = "usbspi"
    NATIVE = "native"


@dataclass(kw_only=True)
class SyncConfig:
    enabled: bool = True
    master: None | Path = None
    group: typing.Optional[int] = None


class Sync:

    def __init__(self):
        self.spi = SpiController()
        self.spi.configure("ftdi://ftdi:232h:1/1")
        self.mosi = self.spi.get_port(cs=0, freq=12e6, mode=0)

    def trigger(self, group_id: int):
        logger.info("Triggering SYNC for group %s.", group_id)
        self.mosi.write([0b11110000, group_id])


if __name__ == "__main__":
    sync = Sync()
    for group_id in range(0, 256):
        sync.trigger(group_id)

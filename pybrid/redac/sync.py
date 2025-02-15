# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import time

from pyftdi.spi import SpiController


class Sync:

    def __init__(self):
        self.spi = SpiController()
        self.spi.configure("ftdi://ftdi:232h:1/1")
        self.mosi = self.spi.get_port(cs=0, freq=12e6, mode=0)

    def trigger(self, group_id):
        # TODO: Allow triggering different SYNC_ID
        self.mosi.write([0b11110000, group_id])


if __name__ == "__main__":
    sync = Sync()
    sync.trigger()

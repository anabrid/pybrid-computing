# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import logging

from pybrid.redac.controller import Controller as REDACController
from pybrid.redac.computer import REDAC
from pybrid.sim.computer import Simulator

logger = logging.getLogger(__name__)

class Controller(REDACController):

    def __init__(self, standalone: bool = False):
        super().__init__(standalone)
        self.computer = Simulator()

    async def enable_udp(self, ctrl_protocol):
        logger.info("Simulator does not support streaming via UDP, staying with TCP...")
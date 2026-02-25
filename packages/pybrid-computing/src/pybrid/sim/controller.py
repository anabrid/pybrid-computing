# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import logging

from pybrid.redac.controller import Controller as REDACController
from pybrid.redac.computer import REDAC
from pybrid.redac.sync import SyncImplementationType
from pybrid.sim.computer import Simulator

logger = logging.getLogger(__name__)

class Controller(REDACController):

    def __init__(self, sync_impl: SyncImplementationType = SyncImplementationType.NATIVE):
        """Initialise the Simulator controller.

        Args:
            sync_impl: Synchronisation strategy. Defaults to NATIVE since the
                simulator does not require an external SYNC generator.
        """
        super().__init__(sync_impl)
        self.computer = Simulator()

    async def enable_udp(self, ctrl_protocol):
        logger.info("Simulator does not support streaming via UDP, staying with TCP...")

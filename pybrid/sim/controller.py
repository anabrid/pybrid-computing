# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import logging

from pybrid.sim.computer import Simulator
from pybrid.sim.protocol.protocol import Protocol
from pybrid.redac.controller import Controller as REDACController

logger = logging.getLogger(__name__)

class Controller(REDACController):

    def __init__(self, standalone: bool = False):
        super().__init__(standalone)
        self.computer = Simulator()

    @classmethod
    def get_protocol_implementation(cls):
        """Returns the specific :class:`.Protocol` implementation by this device"""
        return Protocol

    async def set_computer(self, computer: Simulator):
        """
        Change the configuration of all carrier boards and sub-entities on the REDAC.

        :param computer: The :class:`.REDAC` object containing the configuration to be set.
        :return: None
        """

        # send set_sim message
        if computer.sim_config is not None:
            for protocol in self.protocols:
                await protocol.set_sim_config(computer.sim_config)

        # continue configuration as usual
        await super().set_computer(computer)
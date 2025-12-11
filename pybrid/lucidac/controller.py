# Copyright (c) 2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import logging
import warnings
import typing
from collections import defaultdict

from pybrid.redac.computer import REDAC
from pybrid.lucidac.computer import LUCIDAC
from pybrid.lucidac.front_panel import FrontPanel
from pybrid.redac.controller import Controller as REDACController
from pybrid.redac.protocol.protocol import Protocol
from pybrid.redac.entities import Path

logger = logging.getLogger(__name__)

class Controller(REDACController):
    """
    A minimal controller that implements changes to the REDAC controller
    that are required to support an LUCIDAC natively. These changes are:
    - no running proxy, hence the device does not understand virtual MACs such as '00-00-00-00-00-00'
    yet the configuration files use especially this
    - availability of ACL inputs/outputs

    Thus, this controller performs the mapping between the virtual/real hardware ID 
    manually.
    """

    #: Representation of the current configuration of the LUCIDAC.
    computer: LUCIDAC

    def __init__(self, standalone: bool = False):
        self.computer = LUCIDAC(entities=[])
        self.devices = dict()
        self.protocols = defaultdict(set)
        self.runs = dict()
        self._raw_entity_dict = dict()
        self._ongoing_runs = dict()

        self.sync = None
        self.standalone = standalone
        self._callbacks: dict[int, tuple[typing.Callable, list, dict]] = dict()

    @classmethod
    def get_protocol_implementation(cls):
        """Returns the specific :class:`.Protocol` implementation by this device"""
        return Protocol

    async def add_device(self, host, port, name=None):
        """
        Overwrite REDAC's add_device function to check and store the real entity
        ID.
        """

        # initialize as REDAC first (ignores the )
        await super().add_device(host, port, name=name)

        if len(self.devices) != 1 or len(self.protocols) != 1 or len(self._raw_entity_dict) != 1:
            raise Exception(f"Failed adding LUCIDAC {host}:{port}")

        # initialize the front panel (which is assumed to be there)
        self.computer.front_panel = FrontPanel(self.computer.carriers[0].path / "FP")

        lucidac_mac = list(self._raw_entity_dict.keys())[0][1:]
        logger.info("LUCIDAC entity MAC:" + lucidac_mac)
        
    async def set_computer(self, computer: REDAC):
        """
        Overrides REDAC method for setting configs in order to
        send front panel config as well.
        """

        # send normal config
        await super().set_computer(self.computer)

        # send front panel config
        if self.computer.front_panel is not None:
            protocol = list(self.protocols.keys())[0]
            await protocol.set_configs([self.computer.front_panel])

    async def stop(self):
        for protocol in self.protocols.keys():
            await protocol.stop()

    async def enable_udp(self, ctrl_protocol):
        warnings.warn("LUCIDAC's UDP streaming is currently disabled until we add the LUCIDAC supercontroller...")
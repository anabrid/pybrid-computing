# Copyright (c) 2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

from collections import defaultdict
import logging
import typing
import copy

from pybrid.redac.computer import REDAC

from pybrid.lucidac.computer import LUCIDAC
from pybrid.redac.controller import Controller as REDACController
from pybrid.redac.protocol.protocol import Protocol

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

        self._lucidac_entity: str = None

    @property
    def lucidac_entity(self) -> str:
        return self._lucidac_entity
    
    @classmethod
    def get_protocol_implementation(cls):
        """Returns the specific :class:`.Protocol` implementation by this device"""
        return Protocol

    async def add_device(self, host, port, name=None):
        """
        Overwrite REDAC's add_device function to check and store the real entity
        ID.
        """
        await super().add_device(host, port, name=name)

        assert(len(self.devices) == 1)
        assert(len(self.protocols) == 1)
        assert(len(self._raw_entity_dict) == 1)
        self._lucidac_entity = list(self._raw_entity_dict.keys())[0][1:]
        logger.info("LUCIDAC entity MAC:" + self._lucidac_entity)
        
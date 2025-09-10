# Copyright (c) 2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import logging
import typing


from ..redac.computer import REDAC
from .config import SimConfig
from .protocol.protocol import Protocol

logger = logging.getLogger(__name__)

class Simulator(REDAC):

    #: Simulation config: configuraton data for the REDAC/LUCIDAC simulation, sent via seperate message.
    sim_config: typing.Optional[SimConfig] = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    @property
    def name(self) -> str:
        return "Simulator"

    @classmethod
    def get_timeout(cls) -> int:
        return 30
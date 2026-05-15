# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import logging
from typing import List

import pybrid.base.proto.main_pb2 as pb
from pybrid.redac.computer import REDAC
from pybrid.redac.controller import Controller as REDACController
from pybrid.redac.entities import Path
from pybrid.sim.computer import Simulator

logger = logging.getLogger(__name__)


class Controller(REDACController):

    def __init__(self):
        """Initialise the Simulator controller."""
        super().__init__()
        self.computer = Simulator()

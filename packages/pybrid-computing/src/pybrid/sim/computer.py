# Copyright (c) 2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import logging
from dataclasses import dataclass
from typing import List

import pybrid.base.proto.main_pb2 as pb
from pybrid.redac.computer import REDAC
from pybrid.redac.entities import Entity, Path
from pybrid.sim.config import SimConfig, SimConfigEntity
from pybrid.sim.protocol.serializer import SimulatorDeserializer, SimulatorSerializer

logger = logging.getLogger(__name__)


class Simulator(REDAC):
    """
    A simulator device capable of simulating all REDAC-like devies. Note that a
    simulator does not simulate a specific _hardware_ but is user-configurable.

    At runtime, users can connect via add_device and assign a hardware config that
    will allow configuration of the simulator.
    """

    #: Simulation config sent as a separate top-level message alongside entity configs.
    sim_config: SimConfigEntity = SimConfigEntity(Path())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # register SimConfig on the global level
        self._entities_by_path[Path()] = self.sim_config

    @property
    def name(self) -> str:
        return "Simulator"

    @classmethod
    def get_timeout(cls) -> int:
        return 30

    def get_config_entities(self) -> List[Entity]:
        return [*self.entities, self.sim_config]

    def global_entities(self) -> List[Entity]:
        return [self.sim_config]

    def get_serializer(self) -> type:
        return SimulatorSerializer

    def get_deserializer(self) -> type:
        return SimulatorDeserializer

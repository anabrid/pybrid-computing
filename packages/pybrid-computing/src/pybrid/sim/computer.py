# Copyright (c) 2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import logging
from typing import List
from dataclasses import dataclass

import pybrid.base.proto.main_pb2 as pb

from pybrid.redac.computer import REDAC
from pybrid.sim.config import SimConfig
from pybrid.redac.entities import Entity, Path
from pybrid.sim.config import SimConfigEntity
from pybrid.sim.protocol.serializer import SimulatorSerializer, SimulatorDeserializer

logger = logging.getLogger(__name__)



class Simulator(REDAC):

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

    def get_serializer_implementation(self) -> type:
        return SimulatorSerializer

    def get_deserializer_implementation(self) -> type:
        return SimulatorDeserializer
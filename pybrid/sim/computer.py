# Copyright (c) 2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import logging
import typing
from dataclasses import dataclass

import pybrid.base.proto.main_pb2 as pb
from pybrid.redac.entities import Entity, Path
from pybrid.redac.computer import REDAC
from pybrid.sim.config import SimConfig
from pybrid.redac.entities import Entity, EntityType, EntityClass

logger = logging.getLogger(__name__)

@EntityType.register(EntityClass.OTHER)
@dataclass(kw_only=True)
class SimConfigEntity(Entity, SimConfig):
    """
    Anchors sim config in the "global" entity, with empty path.
    """
    pass

class Simulator(REDAC):

    #: Simulation config: configuration data for the REDAC/LUCIDAC simulation, sent via seperate message.
    sim_config: typing.Optional[SimConfigEntity] = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    @property
    def name(self) -> str:
        return "Simulator"

    @classmethod
    def get_timeout(cls) -> int:
        return 30
    
    def build_config(self, entities: typing.List[Entity | None]):
        """
        Generates a PB-based list of config messages for the given
        list of entities. Imports a serializer for `sim_config`.
        """

        # import all required to_pb overrides
        import pybrid.redac.protocol.serializer
        import pybrid.sim.protocol.serializer        
        from pybrid.base.hybrid.serializer import entities_to_config

        configs = []
        for entity in entities:
            if entity is not None:
                configs += entities_to_config(entity)

        return configs
    
    def global_entities(self) -> typing.List[Entity | None]:
        """
        Returns global entities not represented in the device structure, i.e,
        anchored at the (empty) root path - here the sim config.
        """
        return [self.sim_config]
    
    def to_pb(self) -> typing.List[pb.Config]:
        return self.build_config([
            *self.carriers,
            self.sim_config
        ])
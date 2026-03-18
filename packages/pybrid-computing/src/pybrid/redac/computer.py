# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import logging
from typing import List

import pybrid.base.proto.main_pb2 as pb
from pybrid.redac.entities import Entity, Path, Loc
from pybrid.base.hybrid import AnalogComputer
from pybrid.base.hybrid.utils import build_entity_path_dict
from pybrid.redac.blocks import FunctionBlock
from pybrid.redac.carrier import Carrier, ADCChannel
from pybrid.redac.cluster import Cluster
from pybrid.redac.elements import ComputationElement
from pybrid.redac.entities import Path
from pybrid.redac.router import Router
from pybrid.redac.protocol.serializer import REDACSerializer, REDACDeserializer

logger = logging.getLogger(__name__)


class DAQ:
    computer: "REDAC"

    def __init__(self, computer):
        self.computer = computer
        self._next_probe_index: int = 0

    def capture(self, *entities, gain=1.0, offset=0.0):
        for entity in entities:
            # TODO: entities should have a pybrid.redac.entities.path object with to_carrier() function
            carrier: Carrier = self.computer.get_entity(entity.path.to_root())
            probe_index = self._next_probe_index
            self._next_probe_index += 1
            adc_channel = ADCChannel(index=carrier.resolve_signal(entity), gain=gain, offset=offset, probe=probe_index)
            carrier.adc_config.append(adc_channel)

    def reset(self):
        self._next_probe_index: int = 0

class REDAC(AnalogComputer):
    """
    Representation of the REDAC analog computer and its structure.
    """

    hierarchy = (Carrier, Cluster, FunctionBlock, ComputationElement)
    entities: list[Carrier]

    daq: DAQ
    router: Router

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.daq = DAQ(self)
        self.router = Router()

    @property
    def name(self) -> str:
        return "REDAC"

    def reset(self):
        super().reset()
        self.daq.reset()

    @property
    def carriers(self) -> list[Carrier]:
        """The list of :class:`.Carrier` boards in this REDAC."""
        return self.entities

    def __repr__(self):
        return repr(self.entities)

    def add_carrier(self, carrier: Carrier):
        self.carriers.append(carrier)
        self._entities_by_path.update(build_entity_path_dict([carrier]))
        self.router.add_carrier(carrier)

    def get_config_entities(self) -> List[Entity]:
        return self.entities

    def global_entities(self) -> List[Entity]:
        return []

    def get_serializer(self) -> type:
        return REDACSerializer

    def get_deserializer(self) -> type:
        return REDACDeserializer

    def find_cluster(self, loc: Loc):
        for carrier in self.carriers:
            if loc.carrier() == carrier.location:
                return carrier.clusters[loc.cluster_id()]
        raise Exception(f"Cluster not found for Loc: {loc.cluster()}")

    def route(self, src_math: int, src_lane: Loc, sink_lane: Loc, sink_math: int, coefficient: float):
        """Route between math elements across carriers, including U/C/I block config.

        Args:
            src_math: math lane of source
            src_lane: coef lane of source
            sink_lane:  i lane of sink
            sink_math:  math lane of sink
            coefficient: The C-block weight to apply on the source lane.
        """
        src_cluster = self.find_cluster(src_lane.cluster())
        tgt_cluster = self.find_cluster(sink_lane.cluster())

        # 1. U-block: connect source element to output lane
        src_cluster.ublock.connect(src_math, src_lane.lane_id())

        # 2. C-block: set coefficient on the output lane
        src_cluster.cblock.elements[src_lane.lane_id()].factor = coefficient

        # 3. T-block: route between carriers (existing logic, uses lane-level Loc)
        self.router.route(src_lane, sink_lane)

        # 4. I-block: connect incoming lane to target element
        tgt_cluster.iblock.connect(sink_lane.lane_id(), sink_math)
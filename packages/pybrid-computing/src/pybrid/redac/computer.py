# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import json
import logging
from typing import List, TextIO
import warnings
from pathlib import Path as FilePath

from pydantic.json import pydantic_encoder

import pybrid.base.proto.main_pb2 as pb
from pybrid.redac.entities import Entity, Path
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

    def capture(self, *entities, gain=1.0, offset=0.0):
        for entity in entities:
            # TODO: entities should have a pybrid.redac.entities.path object with to_carrier() function
            carrier: Carrier = self.computer.get_entity(entity.path.to_root())
            adc_channel = ADCChannel(index=carrier.resolve_signal(entity), gain=gain, offset=offset)
            carrier.adc_config.append(adc_channel)


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

    @property
    def carriers(self) -> list[Carrier]:
        """The list of :class:`.Carrier` boards in this REDAC."""
        return self.entities

    def __repr__(self):
        return repr(self.entities)

    def add_carrier(self, carrier: Carrier):
        self.carriers.append(carrier)
        self._entities_by_path.update(build_entity_path_dict([carrier]))
        try:
            self.router.add_carrier(carrier)
        except Exception as exc:
            logger.warning("Could not add carrier to router: %s", exc)

    @classmethod
    def create_from_entity_type_tree(cls, type_tree):
        carriers = []
        for sub_path, sub_tree in type_tree.items():
            carrier = Carrier.create_from_entity_type_tree(Path.parse(sub_path), sub_tree)
            carriers.append(carrier)
        return cls(entities=carriers)

    @classmethod
    def create_from(cls, data):
        """
        Create a computer instance from a given hardware structure.

        The function accepts the following data sources
         - dict representing an entity type tree
         - path to a file containing a json encoded entity type tree
         - file descriptor to such a file
        """
        if isinstance(data, dict):
            entity_tree = data
        elif isinstance(data, TextIO):
            entity_tree = json.load(data)
        elif isinstance(data, str | FilePath):
            with open(data) as fs:
                entity_tree = json.load(fs)
        return REDAC.create_from_entity_type_tree(entity_tree)
    
    def get_config_entities(self) -> List[Entity]:
        return self.entities

    def global_entities(self) -> List[Entity]:
        return []

    def get_serializer_implementation(self) -> type:
        return REDACSerializer

    def get_deserializer_implementation(self) -> type:
        return REDACDeserializer
# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import json
import logging
import typing
import warnings
from contextlib import nullcontext
from pathlib import Path as FilePath

from pydantic.json import pydantic_encoder

import pybrid.base.proto.main_pb2 as pb
from pybrid.redac.entities import Entity, Path
from pybrid.base.hybrid import AnalogComputer
from pybrid.base.hybrid.utils import build_entity_path_dict
from pybrid.redac.blocks import FunctionBlock
from pybrid.redac.carrier import Carrier
from pybrid.redac.cluster import Cluster
from pybrid.redac.elements import ComputationElement
from pybrid.redac.entities import Path
from pybrid.redac.router import Router

logger = logging.getLogger(__name__)


class DAQ:
    computer: "REDAC"

    def __init__(self, computer):
        self.computer = computer

    def capture(self, *entities):
        changed_carriers = []
        for entity in entities:
            # TODO: entities should have a pybrid.redac.entities.path object with to_carrier() function
            carrier: Carrier = self.computer.get_entity(entity.path.to_root())
            adc_channel = carrier.resolve_signal(entity)
            if adc_channel not in carrier.adc_channels:
                carrier.adc_channels.append(adc_channel)
                changed_carriers.append(carrier)
            else:
                warnings.warn("Signal is already being captured, ignoring duplicate capture request.")
        return changed_carriers


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

    def global_entities(self) -> typing.List[Entity | None]:
        return []

    # ██████  ███████        ██ ███████ ███████ ██████  ██  █████  ██      ██ ███████  █████  ████████ ██  ██████  ███    ██
    # ██   ██ ██            ██  ██      ██      ██   ██ ██ ██   ██ ██      ██    ███  ██   ██    ██    ██ ██    ██ ████   ██
    # ██   ██ █████ █████  ██   ███████ █████   ██████  ██ ███████ ██      ██   ███   ███████    ██    ██ ██    ██ ██ ██  ██
    # ██   ██ ██          ██         ██ ██      ██   ██ ██ ██   ██ ██      ██  ███    ██   ██    ██    ██ ██    ██ ██  ██ ██
    # ██████  ███████    ██     ███████ ███████ ██   ██ ██ ██   ██ ███████ ██ ███████ ██   ██    ██    ██  ██████  ██   ████

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
        elif isinstance(data, typing.TextIO):
            entity_tree = json.load(data)
        elif isinstance(data, str | FilePath):
            with open(data) as fs:
                entity_tree = json.load(fs)
        return REDAC.create_from_entity_type_tree(entity_tree)
        
    def build_config(self, entities: typing.List[Entity | None]):
        """
        Generates a PB-based list of config messages for the given
        list of entities. Uses only default serialixers.
        """

        # import all required to_pb overrides
        import pybrid.redac.protocol.serializer
        from pybrid.base.hybrid.serializer import entities_to_config

        configs = []
        for entity in entities:
            if entity is not None:
                configs += entities_to_config(entity)

        return configs
        
    def to_pb(self) -> typing.List[pb.Config]:
        return self.build_config(self.entities)


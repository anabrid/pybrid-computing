# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import logging

from pybrid.base.hybrid import AnalogComputer
from pybrid.base.hybrid.utils import build_entity_path_dict

from .blocks import FunctionBlock
from .carrier import Carrier
from .cluster import Cluster
from .elements import ComputationElement
from .entities import Path
from .router import Router

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
            carrier.adc_channels.append(adc_channel)
            changed_carriers.append(carrier)
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

    @classmethod
    def create_from_entity_type_tree(cls, type_tree):
        carriers = []
        for sub_path, sub_tree in type_tree.items():
            carrier = Carrier.create_from_entity_type_tree(Path.parse(sub_path), sub_tree)
            carriers.append(carrier)
        return cls(entities=carriers)

    def __repr__(self):
        return repr(self.entities)

    def add_carrier(self, carrier: Carrier):
        self.carriers.append(carrier)
        self._entities_by_path.update(build_entity_path_dict([carrier]))
        try:
            self.router.add_carrier(carrier)
        except Exception as exc:
            logger.warning("Could not add carrier to router: %s", exc)

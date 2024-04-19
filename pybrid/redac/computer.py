# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

from pybrid.base.hybrid import AnalogComputer

from .blocks import FunctionBlock
from .carrier import Carrier
from .cluster import Cluster
from .elements import ComputationElement
from .entities import Path


class REDAC(AnalogComputer):
    """
    Representation of the REDAC analog computer and its structure.
    """
    hierarchy = (Carrier, Cluster, FunctionBlock, ComputationElement)
    entities: list[Carrier]

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
            carrier = Carrier.create_from_entity_type_tree(Path((sub_path,)), sub_tree)
            carriers.append(carrier)
        return cls(entities=carriers)

    def __repr__(self):
        return repr(self.entities)




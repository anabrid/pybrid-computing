# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import typing
from dataclasses import dataclass

from ..entities import Entity, EntityType
from ..elements import ComputationElement


class FunctionBlock(Entity):
    @classmethod
    def create_from_entity_type_tree(cls, sub_path, sub_tree):
        # TODO: Refactor out common code
        # Check information on self
        this_entity_type = EntityType.pop_from_dict(sub_tree)

        # Generate type-specific entity
        entity_class = EntityType.lookup(this_entity_type, decay=True)
        return entity_class(path=sub_path)


@dataclass(kw_only=True)
class ElementBlock(FunctionBlock):
    """
    Base class for function blocks in a REDAC.
    """
    ELEMENTS: typing.ClassVar[list[typing.Type[ComputationElement]]] = None
    elements: typing.Optional[list[ComputationElement]] = None

    @property
    def children(self):
        if not self.elements:
            return
        yield from self.elements

    def __post_init__(self):
        super().__post_init__()
        if self.elements is None:
            self.elements = self.initialize_elements(self.path)

    @classmethod
    def initialize_elements(cls, base_path) -> list[ComputationElement]:
        if not cls.ELEMENTS:
            return []
        elements: list[ComputationElement] = list(
            E(path=base_path / idx)
            for idx, E in enumerate(cls.ELEMENTS)
        )
        return elements


class SignalConnectionError(Exception):
    pass


@dataclass
class SwitchingBlock(FunctionBlock):
    def connect(self, *connections, force=False):
        raise NotImplementedError

# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import typing
import warnings
from dataclasses import dataclass

from pybrid.base.proto import main_pb2 as pb
from pybrid.redac.elements import ComputationElement
from pybrid.redac.entities import Entity


class FunctionBlock(Entity):
    @classmethod
    def create_from_entity_type_tree(cls, sub_path, sub_tree: pb.Entity):
        warnings.warn(
            "create_from_entity_type_tree is deprecated. Use REDACDeserializer instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        from pybrid.redac.protocol.serializer import REDACDeserializer
        return REDACDeserializer().deserialize_specification(sub_tree, sub_path)


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
        elements: list[ComputationElement] = list(E(path=base_path / str(idx)) for idx, E in enumerate(cls.ELEMENTS))
        return elements


class SignalConnectionError(Exception):
    pass


@dataclass
class SwitchingBlock(FunctionBlock):
    def connect(self, input, output, *outputs, force=False):
        raise NotImplementedError

# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import typing
from dataclasses import dataclass, field

from pybrid.base.analog import BaseComputation

from .entities import Entity


@dataclass(kw_only=True)
class BaseComputationElement(Entity):
    #: The computation done by this element.
    computation: BaseComputation

    def __hash__(self):
        return hash(self.path)

    def __setattr__(self, key, value):
        # Forward setting attributes to computation if possible
        if key != "computation" and hasattr(self, "computation") and hasattr(self.computation, key):
            setattr(self.computation, key, value)
        else:
            super().__setattr__(key, value)

    def __getattr__(self, item):
        # Forward getting attributes to computation if possible
        if item != "computation" and hasattr(self.computation, item):
            return getattr(self.computation, item)
        raise AttributeError


class ComputationElementMeta(type):
    """
    Allows using ComputationElement[Integration] to generate an integration element.
    """

    def __getitem__(self, computation: typing.Type[BaseComputation]) -> typing.Type[BaseComputationElement]:
        # TODO: Clean this up :)
        return dataclass(
            type(
                computation.__name__ + 'Element', (self,),
                {"__annotations__": {"computation": computation,
                                     "computation_class": typing.ClassVar[typing.Type[computation]]},
                 "computation": field(default_factory=computation), "computation_class": computation,
                 "__hash__": BaseComputationElement.__hash__}
            )
        )


@dataclass(kw_only=True)
class ComputationElement(BaseComputationElement, metaclass=ComputationElementMeta):

    def __hash__(self):
        return hash(self.path)

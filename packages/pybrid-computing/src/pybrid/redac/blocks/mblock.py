# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

from dataclasses import field, dataclass
from enum import Enum

from pybrid.redac.blocks.block import ElementBlock
from pybrid.redac.computations import (
    Integration, Multiplication, MDROperation
)
from pybrid.redac.elements import ComputationElement
from pybrid.redac.entities import EntityClass, EntityType


@EntityType.register(EntityClass.MBLOCK, None)
class MBlock(ElementBlock):
    """
    A general math block (M-Block) in a REDAC. Has 8 inputs and 8 outputs.
    """
    pass


@EntityType.register(EntityClass.MBLOCK, 1)
@dataclass(kw_only=True)
class MIntBlock(MBlock):
    """
    A math block consisting of eight integrators.
    """

    ELEMENTS = (ComputationElement[Integration],) * 8
    elements: list[ComputationElement[Integration]]
    limiters: list[bool] = field(default_factory=lambda: [False] * 8)
    """
    List of elements on the block.
    In case of the MIntBlock, these are eight integration computation elements.
    Each integrator accepts configuration according to :class:`pybrid.redac.computations.Integration`.
    """

    def reset(self):
        self.limiters = [False] * 8
        for element in self.elements:
            element.reset()

@EntityType.register(EntityClass.MBLOCK, 2)
class MMulBlock(MBlock):
    """
    A math block consisting of multiplicative elements.
    """

    ELEMENTS = (ComputationElement[Multiplication],) * 4

@EntityType.register(EntityClass.MBLOCK, 3)
class MMDRBlock(MBlock):
    """
    A math block consisting of MDR elements which offer multiple types of
    operations set during configuration. Note that both inputs and outputs
    MUST always be within [1-.0, 1.0] or else the block may deliver wrong results
    even after a parameter change.
    """

    #: actual computational elements - type determines the operation, i.e.,
    #: these need to be configured at all times with exactly 4 members
    ELEMENTS = (ComputationElement[MDROperation],) * 4
    elements: list[ComputationElement[MDROperation]]

    def reset(self):
        for element in self.elements:
            element.reset()
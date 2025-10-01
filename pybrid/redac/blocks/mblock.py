# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

from dataclasses import field, dataclass

from pybrid.redac.blocks.block import ElementBlock
from pybrid.redac.computations import Integration, Multiplication
from pybrid.redac.elements import ComputationElement
from pybrid.redac.entities import EntityClass, EntityType


@EntityType.register(EntityClass.MBLOCK, None)
class MBlock(ElementBlock):
    """
    A math block (M-Block) in a REDAC.
    """


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


@EntityType.register(EntityClass.MBLOCK, 2)
class MMulBlock(MBlock):
    """
    A math block consisting of multiplicative elements.
    """

    ELEMENTS = (ComputationElement[Multiplication],) * 4

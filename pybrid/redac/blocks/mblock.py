# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

from .block import ElementBlock
from ..computations import Integration, Multiplication
from ..elements import ComputationElement
from ..entities import EntityClass, EntityType


@EntityType.register(EntityClass.MBLOCK, None, None, None)
class MBlock(ElementBlock):
    """
    A math block (M-Block) in a REDAC.
    """


@EntityType.register(EntityClass.MBLOCK, 0, 0, 0)
class MIntBlock(MBlock):
    """
    A math block consisting of eight integrators.
    """
    ELEMENTS = (ComputationElement[Integration],) * 8
    elements: list[ComputationElement[Integration]]
    """
    List of elements on the block.
    In case of the MIntBlock, these are eight integration computation elements.
    Each integrator accepts configuration according to :class:`pybrid.redac.computations.Integration`.
    """


@EntityType.register(EntityClass.MBLOCK, 1, 0, 0)
class MMulBlock(MBlock):
    """
    A math block consisting of multiplicative elements.
    """
    ELEMENTS = (ComputationElement[Multiplication],) * 4

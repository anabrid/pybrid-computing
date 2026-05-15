# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

from pybrid.redac.blocks.block import ElementBlock
from pybrid.redac.computations import ScalarMultiplication
from pybrid.redac.elements import ComputationElement
from pybrid.redac.entities import EntityClass, EntityType


@EntityType.register(EntityClass.CBLOCK)
class CBlock(ElementBlock):
    """
    A coefficient block (C-Block) in a REDAC.
    It can multiply each of the 32 input signal with an individual fixed scalar factor.
    """

    #: List of elements on the block. In case of the CBlock,
    #: these are 32 scalar multiplication computation elements (so-called coefficients).
    #: Each coefficient accepts configuration parameters according to
    #: :class:`pybrid.redac.computations.ScalarMultiplication`.
    elements: list[ComputationElement[ScalarMultiplication]]
    ELEMENTS = (ComputationElement[ScalarMultiplication],) * 32

    def reset(self):
        for element in self.elements:
            element.reset()

# Copyright (c) 2022 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
#
# This file is part of the pyanabrid software packet.
#
# ANABRID_BEGIN_LICENSE:GPL
# Commercial License Usage
# Licensees holding valid commercial anabrid licenses may use this file in
# accordance with the commercial license agreement provided with the
# Software or, alternatively, in accordance with the terms contained in
# a written agreement between you and Anabrid GmbH. For licensing terms
# and conditions see https://www.anabrid.com/licensing. For further
# information use the contact form at https://www.anabrid.com/contact.
#
# GNU General Public License Usage
# Alternatively, this file may be used under the terms of the GNU
# General Public License version 3 as published by the Free Software
# Foundation and appearing in the file LICENSE.GPL3 included in the
# packaging of this file. Please review the following information to
# ensure the GNU General Public License version 3 requirements
# will be met: https://www.gnu.org/licenses/gpl-3.0.html.
# For Germany, additional rules exist. Please consult /LICENSE.DE
# for further agreements.
# ANABRID_END_LICENSE

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
    Each integrator accepts configuration according to :class:`pyanabrid.redac.computations.Integration`.
    """


@EntityType.register(EntityClass.MBLOCK, 1, 0, 0)
class MMulBlock(MBlock):
    """
    A math block consisting of multiplicative elements.
    """
    ELEMENTS = (ComputationElement[Multiplication],) * 4

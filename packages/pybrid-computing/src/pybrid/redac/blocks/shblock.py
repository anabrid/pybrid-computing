# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

from pybrid.redac.blocks import FunctionBlock
from pybrid.redac.entities import EntityType, EntityClass


@EntityType.register(EntityClass.SHBLOCK)
class SHBlock(FunctionBlock):
    pass

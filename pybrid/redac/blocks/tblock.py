# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

from dataclasses import field, dataclass

from .block import FunctionBlock
from ..entities import EntityClass, EntityType


@EntityType.register(EntityClass.TBLOCK)
@dataclass
class TBlock(FunctionBlock):
    muxes: list[int] = field(default_factory=lambda: [0, 1, 2, 3] * 24)

# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

from dataclasses import field, dataclass
from ipaddress import IPv4Address

from .block import FunctionBlock
from ..entities import EntityClass, EntityType, Loc


@EntityType.register(EntityClass.TBLOCK)
@dataclass
class TBlock(FunctionBlock):
    muxes: list[int] = field(default_factory=lambda: [0, 1, 2, 3] * 24)
    sources: dict[int, str] = field(default_factory=lambda: {})

    def connect(self, src_sector: int, dst_sector: int, sector_lane: int):
        dst_lane = sector_lane * 4 + dst_sector
        self.muxes[dst_lane] = src_sector

    def loc(self) -> "Loc":
        elems = self.path.root.split("-")
        if self.path[-1] == "T":
            return Loc.new_carrier(int(elems[0]), int(elems[2]), int(elems[5]))
        elif self.path[-1] == "ST0":
            return Loc.new_wing(int(elems[0]), 0)
        elif self.path[-1] == "ST1":
            return Loc.new_wing(int(elems[0]), 1)
        else:
            raise NotImplementedError()

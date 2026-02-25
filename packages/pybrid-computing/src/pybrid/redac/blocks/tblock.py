# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

from dataclasses import field, dataclass

from pybrid.redac.blocks.block import FunctionBlock
from pybrid.redac.entities import EntityClass, EntityType, Loc


@EntityType.register(EntityClass.TBLOCK)
@dataclass
class TBlock(FunctionBlock):
    muxes: list[int] = field(default_factory=lambda: [0, 1, 2, 3] * 24)

    @staticmethod
    def index(dst_sector: int, sector_lane: int):
        return sector_lane * 4 + dst_sector

    def connect(self, src_sector: int, dst_sector: int, sector_lane: int):
        if not (0 <= src_sector < 4):
            raise Exception("Connections between cluster only allowed between 0 to 3! (0: backplane, 1-3: cluster)")

        if not (0 <= dst_sector < 4):
            raise Exception("Connections between cluster only allowed between 0 to 3! (0: backplane, 1-3: cluster)")

        if not (0 <= sector_lane < 24):
            raise Exception("Connections between cluster only allowed between 0 to 23 lane indices!")

        self.muxes[TBlock.index(dst_sector, sector_lane)] = src_sector

    def source(self, dst_sector: int, sector_lane: int):
        return self.muxes[TBlock.index(dst_sector, sector_lane)]

    def loc(self) -> "Loc":
        elems = self.path.root.split("-")
        if self.path[-1] == "T":
            return Loc.new_carrier(int(elems[0], base=16), int(elems[5], base=16))
        else:
            raise NotImplementedError()

    def reset(self):
        self.muxes = [0, 1, 2, 3] * 24

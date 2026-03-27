# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

from typing import Optional
from dataclasses import field, dataclass

from pybrid.redac.blocks.block import FunctionBlock
from pybrid.redac.entities import EntityClass, EntityType, Loc


@EntityType.register(EntityClass.TBLOCK)
@dataclass
class TBlock(FunctionBlock):
    muxes: list[int | None] = field(default_factory=lambda: [None] * 24 * 4)

    @staticmethod
    def index(dst_sector: int, sector_lane: int):
        assert 0 <= dst_sector < 4
        assert 0 <= sector_lane < 24
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

    def reset(self):
        self.muxes = [None] * (24 * 4)

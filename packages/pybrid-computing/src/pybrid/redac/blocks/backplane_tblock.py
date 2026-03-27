# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

from dataclasses import field, dataclass
from ipaddress import IPv4Address

from pybrid.redac.blocks.block import FunctionBlock
from pybrid.redac.entities import EntityClass, EntityType, Loc


@EntityType.register(EntityClass.T_BLOCK_BPL)
@dataclass
class BackplaneTBlock(FunctionBlock):
    muxes: list[int | None] = field(default_factory=lambda: [None] * 8 * 9)

    @staticmethod
    def index(dst_sector: int, sector_lane: int) -> int:
        assert 0 <= sector_lane < 8
        assert 0 <= dst_sector < 9
        return dst_sector + sector_lane * 9

    def connect(self, src_sector: int, dst_sector: int, sector_lane: int):
        assert 0 <= src_sector < 9
        self.muxes[BackplaneTBlock.index(dst_sector, sector_lane)] = src_sector

    def source(self, dst_sector: int, sector_lane: int) -> int:
        return self.muxes[BackplaneTBlock.index(dst_sector, sector_lane)]

    def reset(self):
        self.muxes = [None] * 8 * 9

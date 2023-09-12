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

import typing
from dataclasses import dataclass

from .entities import Entity, Path, EntityType, EntityClass
from .blocks import FunctionBlock, MBlock, UBlock, CBlock, IBlock


@dataclass(kw_only=True)
class Cluster(Entity):
    """
    A REDAC computation cluster.
    """
    m1block: typing.Optional[MBlock]
    m2block: typing.Optional[MBlock]
    ublock: UBlock
    cblock: CBlock
    iblock: IBlock

    @property
    def children(self):
        yield from (block for block in self.blocks if block is not None)

    @property
    def blocks(self) -> tuple[typing.Optional[MBlock], typing.Optional[MBlock], UBlock, CBlock, IBlock]:
        return self.m1block, self.m2block, self.ublock, self.cblock, self.iblock

    @classmethod
    def create_from_entity_type_tree(cls, path, tree):
        # TODO: Refactor out common code
        # Check information on self
        this_entity_type = EntityType.pop_from_dict(tree)
        assert this_entity_type.class_ is EntityClass.CLUSTER

        # Generate child entities
        blocks = []
        for sub_path, sub_tree in tree.items():
            if not sub_path.startswith('/'):
                raise ValueError('Unexpected entities tree element. Expected only sub-paths to be left.')
            path_ = path / Path((sub_path.removeprefix('/'),))
            block = FunctionBlock.create_from_entity_type_tree(path_, sub_tree)
            blocks.append(block)

        # TODO: Less hard-coding :)
        return cls(path=path, m1block=blocks[0], m2block=blocks[1], ublock=blocks[2], cblock=blocks[3], iblock=blocks[4])

    def route(self, m_out, u_out, c_factor, m_in):
        # TODO: Sanity checks and error handling
        self.ublock.connect(m_out, u_out)
        self.cblock.elements[u_out].factor = c_factor
        self.iblock.connect(u_out, m_in)

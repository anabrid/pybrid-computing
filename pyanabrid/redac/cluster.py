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

    The cluster is the smallest unit capable of an analog computation.
    It always consists of two optional :class:`.blocks.MBlock` objects
    and one mandatory :class:`.blocks.UBlock`, :class:`.blocks.CBlock` and :class:`.blocks.IBlock` each.
    """
    #: The first :class:`.blocks.MBlock` in this cluster. May be ``None`` if the slot is not filled.
    m0block: typing.Optional[MBlock]
    #: The second :class:`.blocks.MBlock` in this cluster. May be ``None`` if the slot is not filled.
    m1block: typing.Optional[MBlock]
    #: The :class:`.blocks.UBlock` in this cluster.
    ublock: UBlock
    #: The :class:`.blocks.CBlock` in this cluster.
    cblock: CBlock
    #: The :class:`.blocks.IBlock` in this cluster.
    iblock: IBlock

    @property
    def children(self):
        """
        Generator iterating through child entities of type :class:`.blocks.FunctionBlock`.
        Only returns blocks that are actually present (i.e. not ``None``).
        """
        yield from (block for block in self.blocks if block is not None)

    @property
    def blocks(self) -> tuple[typing.Optional[MBlock], typing.Optional[MBlock], UBlock, CBlock, IBlock]:
        """
        List of :class:`.blocks.FunctionBlock` objects in this cluster.
        Returns ``None`` elements for blocks that are not present.
        """
        return self.m0block, self.m1block, self.ublock, self.cblock, self.iblock

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
        return cls(path=path, m0block=blocks[0], m1block=blocks[1], ublock=blocks[2], cblock=blocks[3],
                   iblock=blocks[4])

    def route(self, m_out: int, u_out: int, c_factor: float, m_in: int):
        """
        Convenience function to connect a signal from before the :class:`.blocks.UBlock` through a coefficient
        on the :class:`.blocks.CBlock` and through the :class:`.blocks.IBlock` to an input on one of the
        :class:`.blocks.MBlock` slots.

        :param int m_out: Output index from one of the MBlocks, respectively input index of the UBlock.
        :param int u_out: Output index of the UBlock, respectively index of the coefficient.
        :param float c_factor: Factor of the coefficient.
        :param int m_in: Input index of one of the MBlocks, respectively output index of the IBlock.
        :return: ``None``
        """
        # TODO: Sanity checks and error handling
        self.ublock.connect(m_out, u_out)
        self.cblock.elements[u_out].factor = c_factor
        self.iblock.connect(u_out, m_in)

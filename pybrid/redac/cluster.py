# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import typing
import warnings
from dataclasses import dataclass

from .blocks import FunctionBlock, MBlock, UBlock, CBlock, IBlock
from .entities import Entity, Path, EntityType, EntityClass


@dataclass(kw_only=True)
class Cluster(Entity):
    """
    A REDAC computation cluster.

    The cluster is the smallest unit capable of an analog computation.
    It always consists of two optional :class:`.blocks.MBlock` objects
    and one mandatory :class:`.blocks.UBlock`, :class:`.blocks.CBlock` and :class:`.blocks.IBlock` each.
    """

    #: The first :class:`.blocks.MBlock` in this cluster. May be ``None`` if the slot is not filled.
    m0block: typing.Optional[MBlock] = None
    #: The second :class:`.blocks.MBlock` in this cluster. May be ``None`` if the slot is not filled.
    m1block: typing.Optional[MBlock] = None
    #: The :class:`.blocks.UBlock` in this cluster.
    ublock: UBlock
    #: The :class:`.blocks.CBlock` in this cluster.
    cblock: CBlock
    #: The :class:`.blocks.IBlock` in this cluster.
    iblock: IBlock
    #: The SHBlock in this cluster.
    shblock: object

    @property
    def children(self):
        """
        Generator iterating through child entities of type :class:`.blocks.FunctionBlock`.
        Only returns blocks that are actually present (i.e. not ``None``).
        """
        yield from (block for block in self.blocks if block is not None)

    @property
    def blocks(
        self,
    ) -> tuple[typing.Optional[MBlock], typing.Optional[MBlock], UBlock, CBlock, IBlock]:
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

        # TODO: Actually use the EUI
        tree.pop("eui", None)

        # Generate child entities
        blocks = dict()
        for sub_path, sub_tree in tree.items():
            if not sub_path.startswith("/"):
                raise ValueError("Unexpected entities tree element. Expected only sub-paths to be left.")
            path_ = path / Path((sub_path.removeprefix("/"),))
            block = FunctionBlock.create_from_entity_type_tree(path_, sub_tree)
            blocks[f"{path_.id_.lower()}block"] = block

        # TODO: Less hard-coding :)
        return cls(path=path, **blocks)

    def set_constant(self, value: bool | float):
        self.ublock.set_constant(value)

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
        if abs(c_factor) > 1.0:
            c_factor = c_factor / 8.0
            if abs(c_factor) > 1.0:
                raise ValueError("Factor is still greater than 1, even after enabling up-scaling.")
            self.iblock.upscaling[u_out] = True
        self.ublock.connect(m_out, u_out)
        self.cblock.elements[u_out].factor = c_factor
        self.iblock.connect(u_out, m_in)

    def add_constant(self, u_out: int, c_factor: float, m_in: int, constant_value: float | bool = 1.0):
        """
        Inject a constant and add it to the math block input `m_in`.

        This replaces the b-group inputs in the U-block with constants, which limits some future connections.
        """
        warnings.warn(
            "Injecting constants prevents some other connections from working as normal. "
            "This is currently not checked, so you need to do it manually."
        )
        self.ublock.set_constant(constant_value)
        u_in = 14 if u_out > 15 else 15
        self.route(u_in, u_out, c_factor, m_in)

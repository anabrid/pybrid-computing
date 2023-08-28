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

from ..entities import Entity, EntityType
from ..elements import ComputationElement


class FunctionBlock(Entity):
    @classmethod
    def create_from_entity_type_tree(cls, sub_path, sub_tree):
        # TODO: Refactor out common code
        # Check information on self
        this_entity_type = EntityType.pop_from_dict(sub_tree)

        # Generate type-specific entity
        entity_class = EntityType.lookup(this_entity_type, decay=True)
        return entity_class(path=sub_path)


@dataclass(kw_only=True)
class ElementBlock(FunctionBlock):
    """
    Base class for function blocks in a REDAC.
    """
    ELEMENTS: typing.ClassVar[list[typing.Type[ComputationElement]]] = None
    elements: typing.Optional[list[ComputationElement]] = None

    @property
    def children(self):
        if not self.elements:
            return
        yield from self.elements

    def __post_init__(self):
        super().__post_init__()
        if self.elements is None:
            self.elements = self.initialize_elements(self.path)

    @classmethod
    def initialize_elements(cls, base_path) -> list[ComputationElement]:
        if not cls.ELEMENTS:
            return []
        elements: list[ComputationElement] = list(
            E(path=base_path / idx)
            for idx, E in enumerate(cls.ELEMENTS)
        )
        return elements


@dataclass
class SwitchingBlock(FunctionBlock):
    def connect(self, *connections):
        raise NotImplementedError

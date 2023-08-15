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

from ..entities import Entity, EntityClass, UnknownEntityTypeError, EntityType


class FunctionBlock(Entity):
    """
    Base class for function blocks in a REDAC.
    """

    @classmethod
    def create_from_entity_type_tree(cls, sub_path, sub_tree):
        # TODO: Refactor out common code
        # Check information on self
        this_entity_type = EntityType.pop_from_dict(sub_tree)

        # Generate child entities
        # TODO: Add auto-registration for custom FunctionBlocks
        # TODO: Consider EntityType.type_ as well to differentiate between MBlock types
        from . import MBlock, UBlock, CBlock, IBlock
        block_classes = {
            EntityClass.MBLOCK: MBlock,
            EntityClass.UBLOCK: UBlock,
            EntityClass.CBLOCK: CBlock,
            EntityClass.IBLOCK: IBlock
        }
        try:
            block_class = block_classes[this_entity_type.class_]
            return block_class(path=sub_path)
        except KeyError as exc:
            raise UnknownEntityTypeError from exc

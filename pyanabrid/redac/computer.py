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
from pyanabrid.base.hybrid import Entity
from pyanabrid.base.hybrid.computer import AnalogComputer

from .blocks import FunctionBlock
from .carrier import Carrier
from .cluster import Cluster
from .entities import Path, EntityType, EntityClass


class REDAC(AnalogComputer):
    hierarchy = (Carrier, Cluster, FunctionBlock)
    entities: list[Carrier]

    @property
    def name(self) -> str:
        return "REDAC"

    @property
    def carriers(self) -> list[Carrier]:
        return self.entities

    @classmethod
    def create_from_entity_type_tree(cls, type_tree):
        carriers = []
        for sub_path, sub_tree in type_tree.items():
            carrier = Carrier.create_from_entity_type_tree(Path((sub_path,)), sub_tree)
            carriers.append(carrier)
        return cls(entities=carriers)

    def __repr__(self):
        return repr(self.entities)




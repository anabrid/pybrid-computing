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

from dataclasses import dataclass
from enum import Enum

from pyanabrid.base.hybrid import Path as BasePath
from pyanabrid.base.hybrid import Entity as BaseEntity


class UnknownEntityTypeError(ValueError):
    pass


class EntityClass(Enum):
    """Entity class differentiates between carrier boards, different function blocks and so on. Max 5bit = 31."""
    CARRIER = 0
    CLUSTER = 1  # mostly unused
    MBLOCK = 2
    UBLOCK = 3
    CBLOCK = 4
    IBLOCK = 5
    OTHER = 31


@dataclass(kw_only=True)
class EntityType:
    class_: EntityClass
    type_: int
    variant: int
    version: int

    @classmethod
    def pop_from_dict(cls, d):
        return cls(class_=EntityClass(d.pop("class")), type_=d.pop("type"), variant=d.pop("variant"), version=d.pop("version"))


class Entity(BaseEntity):
    """
    Base class for all entities inside a REDAC.
    """

    @classmethod
    def create_from_entity_type_tree(cls, sub_path, sub_tree):
        raise NotImplementedError


class Path(BasePath):
    """
    A tuple uniquely identifying an entity in the REDAC.

    The path to an entity is a hierarchical combination of paths to its parent entities.
    Its structure in the REDAC is :code:`(<carrier board>, <cluster>, <block>[, <function>])`.
    Carrier boards are defined by their MAC address, e.g. "04-E9-E5-14-74-BF".
    Clusters are defined by their index sent as a string, e.g. "0".
    Function blocks on them are identified by their abbreviation, one of "M0", "M1", "U", "C", "I".
    The blocks' functions are usually not directly accessed, but instead configured via their block.

    :Usage: Combine the identifier to the required depth

        .. code-block::

            path_to_a_carrier_board = Path("00:00:5e:00:53:af")
            path_to_second_cluster_on_it = Path("00:00:5e:00:53:af", "1")
            path_to_m0_block_in_cluster0 = Path("00:00:5e:00:53:af", "0", "M0")
    """
    #: The schema defining the data types for the path's subcomponents.
    SCHEMA = (str, str, str)

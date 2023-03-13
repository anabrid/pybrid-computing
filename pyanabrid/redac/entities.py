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

from pyanabrid.base.hybrid import Path as BasePath


@dataclass(kw_only=True)
class EntityType:
    class_: int
    type_: int
    variant: int
    version: int


class Path(BasePath):
    """
    A tuple uniquely identifying an entity in the REDAC.

    The path to an entity is a hierarchical combination of paths to its parent entities.
    Its structure in the REDAC is :code:`(<carrier board>, <block>, <function>)`.
    Carrier boards are defined by their MAC address,
    while blocks on them and the blocks' functions are defined by indices.

    :Usage: Combine the identifier to the required depth

        .. code-block::

            path_to_a_carrier_board = Path("00:00:5e:00:53:af")
            path_to_a_block = Path("00:00:5e:00:53:af", 7)
            path_to_a_function = Path("00:00:5e:00:53:af", 7, 42)
    """
    #: The schema defining the data types for the path's subcomponents.
    SCHEMA = (str, int, int)

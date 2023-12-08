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

from .entities import Entity, Path, EntityType, EntityClass
from .cluster import Cluster


@dataclass(kw_only=True)
class Carrier(Entity):
    """
    A REDAC carrier board.

    This is the smallest independent hardware unit inside a REDAC.
    It contains several :class:`.cluster.Cluster` objects.
    """
    #: List of clusters on the carrier board.
    clusters: list[Cluster]

    @property
    def children(self):
        """Generator iterating through child entities of type :class:`.cluster.Cluster`."""
        yield from self.clusters

    @classmethod
    def create_from_entity_type_tree(cls, path, tree):
        # TODO: Refactor out common code
        # Check information on self
        this_entity_type = EntityType.pop_from_dict(tree)
        assert this_entity_type.class_ is EntityClass.CARRIER

        # Generate child entities
        clusters = []
        for sub_path, sub_tree in tree.items():
            if not sub_path.startswith('/'):
                raise ValueError('Unexpected entities tree element. Expected only sub-paths to be left.')
            path_ = path / Path((sub_path.removeprefix('/'),))
            cluster = Cluster.create_from_entity_type_tree(path_, sub_tree)
            clusters.append(cluster)

        return cls(path=path, clusters=clusters)

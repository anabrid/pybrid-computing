# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

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

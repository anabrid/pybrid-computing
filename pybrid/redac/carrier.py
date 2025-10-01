# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import logging
import string
from dataclasses import dataclass, field
from typing import Optional

from pybrid.base.hybrid import EntityDoesNotExist

from pybrid.redac.blocks import TBlock
from pybrid.redac.cluster import Cluster
from pybrid.redac.entities import Entity, Path, EntityType, EntityClass

logger = logging.getLogger(__name__)
import pybrid.base.proto.main_pb2 as pb


@dataclass(kw_only=True)
class Carrier(Entity):
    """
    A REDAC carrier board.

    This is the smallest independent hardware unit inside a REDAC.
    It contains several :class:`.cluster.Cluster` objects.
    """

    adc_channels: list[Optional[int]] = field(default_factory=list)

    #: List of clusters on the carrier board.
    clusters: list[Cluster]
    tblock: TBlock
    st0block: Optional[TBlock] = None
    st1block: Optional[TBlock] = None

    @property
    def children(self):
        """Generator iterating through child entities of type :class:`.cluster.Cluster`."""
        yield from self.clusters
        if self.tblock:
            yield self.tblock
        if self.st0block:
            yield self.st0block
        if self.st1block:
            yield self.st1block

    @classmethod
    def create_from_entity_type_tree(cls, path, tree: pb.Entity):
        # TODO: Refactor out common code
        # Check information on self
        this_entity_type = EntityType.pop_from_dict(tree)
        assert this_entity_type.class_ is EntityClass.CARRIER

        # Generate child entities
        clusters = []
        tblock = None
        st0block = None
        st1block = None
        for child in tree.children:
            #sub_path, sub_tree
            path_: Path = path / Path.parse(child.id)
            if not path_.id_:
                # Sanity check, firmware may report partially broken entities
                logger.warning("Reported entities include nameless entity at %s: %s", path_, child)
                continue
            if path_.id_ == "T":
                tblock = TBlock.create_from_entity_type_tree(path_, child)
                continue
            if path_.id_ == "ST0":
                st0block = TBlock.create_from_entity_type_tree(path_, child)
                continue
            if path_.id_ == "ST1":
                st1block = TBlock.create_from_entity_type_tree(path_, child)
                continue
            if path_.id_ in string.digits:
                cluster = Cluster.create_from_entity_type_tree(path_, child)
                clusters.append(cluster)
                continue

        return cls(path=path, clusters=clusters, tblock=tblock, st0block=st0block, st1block=st1block)

    def resolve_signal(self, entity: "Entity"):
        # TODO: This should be extended to a general approach to defining inputs and outputs of elements
        if not entity.path.to_root() == self.path:
            raise EntityDoesNotExist("Entity does not exist on this carrier.")

        # Currently, we can only resolve signals from M-Blocks
        if not entity.path.depth == 4 or not entity.path[2].startswith("M"):
            raise NotImplementedError("Resolving signals is currently only possible for M-Blocks.")

        cluster_idx = int(entity.path[1])
        m_slot = int(entity.path[2].strip("M"))
        element_idx = int(entity.path.id_)
        return cluster_idx * 16 + m_slot * 8 + element_idx

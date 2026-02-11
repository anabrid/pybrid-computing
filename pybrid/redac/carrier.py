# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

from __future__ import annotations

import logging
import string
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

from pybrid.base.hybrid import EntityDoesNotExist
from pybrid.redac.blocks import TBlock
from pybrid.redac.cluster import Cluster
from pybrid.redac.entities import Entity, Path, EntityType, EntityClass

if TYPE_CHECKING:
    from pybrid.lucidac.front_plane import FrontPlane

logger = logging.getLogger(__name__)
import pybrid.base.proto.main_pb2 as pb

@dataclass(kw_only=True)
class ADCChannel:
    #: index of M-output lane that is converted by this ADC
    index: int
    #: ADC gain - pybrid internally multiplies the output of this ADC with the gain
    gain: float = 1.0
    #: ADC offset - pybrid internally adds this offset to this ADCs' output
    offset: float = 0.0

@dataclass(kw_only=True)
class Carrier(Entity):
    """
    A REDAC carrier board.

    This is the smallest independent hardware unit inside a REDAC.
    It contains several :class:`.cluster.Cluster` objects.

    Note that to avoid sending configs that are dropped by the firmware, thr
    acl_select was moved to the LUCIDAC.
    """

    #: ADCs for DAQ.
    adc_config: list[Optional[ADCChannel]] = field(default_factory=list)

    #: ACL Select for analog I/O - note that while not supported in HW, the firmware ignores this.
    acl_select: Optional[list[str]] = None

    #: List of clusters on the carrier board.
    clusters: list[Cluster]

    #: T-block for REDAC carriers. Optional because LUCIDAC doesn't have T-block.
    tblock: Optional[TBlock] = None
    st0block: Optional[TBlock] = None
    st1block: Optional[TBlock] = None

    #: Optional front plane, currently only available on LUCIDAC carriers.
    front_plane: Optional[FrontPlane] = None

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
        if self.front_plane:
            yield self.front_plane

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
        front_plane = None
        acl_select = None

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
            if path_.id_ == "FP":
                # Firmware reports FP with class_=UNKNOWN(0), so detect by name.
                from pybrid.lucidac.front_plane import FrontPlane as FP
                front_plane = FP(path_)

                acl_select = 8 * ["INTERNAL"]
                continue
            if path_.id_ in string.digits:
                cluster = Cluster.create_from_entity_type_tree(path_, child)
                clusters.append(cluster)
                continue

        return cls(path=path, clusters=clusters, tblock=tblock, st0block=st0block,
            st1block=st1block, front_plane=front_plane, acl_select=acl_select)

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

    @property
    def front_panel(self):
        """Deprecated: use front_plane instead."""
        import warnings
        warnings.warn(
            "Carrier.front_panel is deprecated, use Carrier.front_plane",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.front_plane

    def reset(self):
        """Reset the carrier to its initial configuration."""
        Entity.reset(self)
        self.adc_config = []
        self.acl_select = None
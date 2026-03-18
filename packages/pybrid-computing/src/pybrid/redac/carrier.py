# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

from pybrid.base.hybrid import EntityDoesNotExist
from pybrid.redac.blocks import TBlock
from pybrid.redac.blocks.backplane_tblock import BackplaneTBlock
from pybrid.redac.cluster import Cluster
from pybrid.redac.entities import Entity, Path, EntityType, Loc

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
    #: Probe: relates this ADC channel to an input function (e.g. a problem description, such as an ODE)
    probe: int = -1

@dataclass(kw_only=True)
class Carrier(Entity):
    """
    A REDAC carrier board.

    This is the smallest independent hardware unit inside a REDAC.
    It contains several :class:`.cluster.Cluster` objects.

    The acl_select field lives on LUCIDAC, not here, because the firmware
    ignores carrier-level ACL config messages.
    """

    #: ADCs for DAQ.
    adc_config: list[Optional[ADCChannel]] = field(default_factory=list)

    #: ACL Select for analog I/O - note that while not supported in HW, the firmware ignores this.
    acl_select: Optional[list[str]] = None

    #: List of clusters on the carrier board.
    clusters: list[Cluster]

    #: T-block for REDAC carriers. Optional because LUCIDAC doesn't have T-block.
    tblock: Optional[TBlock] = None
    st0block: Optional[BackplaneTBlock] = None
    st1block: Optional[BackplaneTBlock] = None
    st2block: Optional[BackplaneTBlock] = None

    #: Optional front plane, currently only available on LUCIDAC carriers.
    front_plane: Optional[FrontPlane] = None

    #: Protobuf entity metadata preserved from deserialization (class, type, variant, version).
    #: Used by the description serializer to reproduce the exact entity type fields.
    entity_type: Optional[EntityType] = None

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
        if self.st2block:
            yield self.st2block
        if self.front_plane:
            yield self.front_plane

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
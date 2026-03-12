# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import logging
import typing
import warnings
from dataclasses import dataclass

from pybrid.redac.carrier import Carrier
from pybrid.redac.blocks.backplane_tblock import BackplaneTBlock
from pybrid.redac.entities import Entity

logger = logging.getLogger(__name__)
import pybrid.base.proto.main_pb2 as pb


@dataclass(kw_only=True)
class Device(Entity):
    """
    A REDAC device.

    One device can have multiple carriers.
    Can act like the proxy or a actual hardware device.
    """

    backplane: typing.Optional[BackplaneTBlock] = None
    carriers: typing.List[Carrier]

    @property
    def children(self):
        yield from self.carriers

    @classmethod
    def create_from_entity_type_tree(cls, path, entity: pb.Entity) -> "Device":
        warnings.warn(
            "create_from_entity_type_tree is deprecated. Use REDACDeserializer instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        from pybrid.redac.protocol.serializer import REDACDeserializer
        return REDACDeserializer().deserialize_specification(entity, path)


# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import logging
import string
import typing
from dataclasses import dataclass, field
from typing import Optional, Any

from pybrid.base.hybrid import EntityDoesNotExist

from pybrid.redac.blocks import TBlock
from pybrid.redac.carrier import Carrier
from pybrid.redac.entities import Entity, Path, EntityType, EntityClass

logger = logging.getLogger(__name__)
import pybrid.base.proto.main_pb2 as pb


@dataclass(kw_only=True)
class Device(Entity):
    """
    A REDAC device.

    One device can have multiple carriers.
    Can act like the proxy or a actual hardware device.
    """

    carriers: typing.List[Carrier]

    @property
    def children(self):
        yield from self.carriers

    @classmethod
    def create_from_entity_type_tree(cls, path, entity: pb.Entity) -> "Device":
        carriers = []

        if entity.class_ == pb.Entity.CARRIER:
            carriers.append(Carrier.create_from_entity_type_tree(path, entity))
        elif entity.class_ == pb.Entity.DEVICE:
            for child in entity.children:
                carrier_path = Path.parse(child.id)
                carrier = Carrier.create_from_entity_type_tree(carrier_path, child)
                carriers.append(carrier)

        return cls(carriers=carriers, path=path)


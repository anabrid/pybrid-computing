# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

from dataclasses import dataclass
from enum import StrEnum


class PartitionMode(StrEnum):
    CARRIER = "carrier"
    WING = "wing"
    STACK = "stack"
    DEVICE = "device"


@dataclass(kw_only=True)
class PartitionConfig:
    mode: PartitionMode = PartitionMode.DEVICE
    id: int = 0

    def remap_virtual_entity_id(self, entity_id: str):
        # Map partition-local entity id (i.e. with range limited by partition size) to global virtual entity id
        # Output format is SS-00-WW-00-00-CC, with S=stack-id, W=wing-id, C=carrier-id
        if self.mode is PartitionMode.DEVICE:
            return entity_id
        elif self.mode is PartitionMode.STACK:
            stack = self.id
            return f"{stack:02d}" + entity_id[2:]
        elif self.mode is PartitionMode.WING:
            stack = self.id // 2
            wing = self.id % 2
            return f"{stack:02d}-00-{wing:02d}-00" + entity_id[11:]
        elif self.mode is PartitionMode.CARRIER:
            stack = self.id // 6
            wing = self.id // 3 % 2
            carrier = self.id % 3
            return f"{stack:02d}-00-{wing:02d}-00-00-{carrier:02d}"
        else:
            raise NotImplementedError(f"Remapping of virtual entity is not implemented for partition mode {self.mode}")

    def inv_remap_virtual_entity_id(self, entity_id):
        # Map global virtual entity id to partition-local entity id
        if self.mode is PartitionMode.DEVICE:
            return entity_id
        elif self.mode is PartitionMode.STACK:
            return "00" + entity_id[2:]
        elif self.mode is PartitionMode.WING:
            return "00-00-00-00" + entity_id[11:]
        elif self.mode is PartitionMode.CARRIER:
            return "00-00-00-00-00-00"

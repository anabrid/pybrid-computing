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
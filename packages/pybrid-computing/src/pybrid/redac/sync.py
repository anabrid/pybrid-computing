# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import logging
import typing
from dataclasses import dataclass
from enum import Enum

from pybrid.redac.entities import Path

logger = logging.getLogger(__name__)


class SyncMode(Enum):
    NONE = None
    STANDALONE = "standalone"
    SLAVE = "slave"
    MASTER = "master"

    def requires_external_sync(self):
        return self is SyncMode.STANDALONE

@dataclass(kw_only=True)
class SyncConfig:
    enabled: bool = True
    master: None | Path = None
    group: typing.Optional[int] = None
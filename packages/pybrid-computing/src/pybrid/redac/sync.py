# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import logging
import typing
from dataclasses import dataclass

from pybrid.redac.entities import Path

logger = logging.getLogger(__name__)


@dataclass(kw_only=True)
class SyncConfig:
    enabled: bool = True
    master: None | Path = None
    group: typing.Optional[int] = None

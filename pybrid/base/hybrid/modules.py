# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

from dataclasses import dataclass

from .entities import Entity


@dataclass(kw_only=True)
class ComputationModule(Entity):
    pass

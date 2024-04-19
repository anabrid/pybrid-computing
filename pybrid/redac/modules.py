# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

from dataclasses import dataclass


class ModuleType(str):
    """Should probably be roughly equal to what we save in metadata storage"""
    pass


@dataclass
class Module:
    pass

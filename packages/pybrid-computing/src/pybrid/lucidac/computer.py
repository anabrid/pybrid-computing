# Copyright (c) 2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
LUCIStack device model.

A ``LUCIStack`` is a stack of one or more LUCIDAC carrier boards.
It extends the REDAC base class with LUCIDAC-specific serialization.

The convenience property ``front_panel`` has been removed; access the
front plane via ``lucistack.entities[0].front_plane`` instead.

Backward-compatible alias: ``LUCIDAC = LUCIStack``.
"""

from __future__ import annotations

from typing import List

from pybrid.redac.entities import Entity
from pybrid.redac.computer import REDAC
from pybrid.lucidac.protocol.serializer import LUCIDACSerializer, LUCIDACDeserializer


class LUCIStack(REDAC):
    """
    Device model for a LUCIDAC stack (one or more LUCIDAC carriers).

    The difference between a REDAC and a LUCIStack is that the LUCIStack
    uses physical MACs rather than virtual entity IDs, and typically
    contains a single carrier with a single cluster plus a front plane.

    The REDAC protocol can be simplified by removing SYNCs when there
    is only one carrier.
    """

    @property
    def name(self) -> str:
        """Return the human-readable device model name."""
        return "LUCIStack"

    def get_config_entities(self) -> List[Entity]:
        """Return the list of top-level entities to serialize."""
        return list(self.entities)

    def get_serializer_implementation(self) -> type:
        """Return the LUCIDAC-specific serializer class."""
        return LUCIDACSerializer

    def get_deserializer_implementation(self) -> type:
        """Return the LUCIDAC-specific deserializer class."""
        return LUCIDACDeserializer


# Backward-compatible alias
LUCIDAC = LUCIStack

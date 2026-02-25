# Copyright (c) 2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
Deprecation shim for the old ``front_panel`` module.

All classes have moved to :mod:`pybrid.lucidac.front_plane`.
Importing from this module still works but is deprecated.

.. deprecated::
    Use ``from pybrid.lucidac.front_plane import FrontPlane`` instead.
"""

import warnings as _warnings

_warnings.warn(
    "pybrid.lucidac.front_panel is deprecated, "
    "use pybrid.lucidac.front_plane instead",
    DeprecationWarning,
    stacklevel=2,
)

# Marker flag so tests can verify this module is a deprecation shim
_DEPRECATED = True

# Re-export all public names from the canonical module
from pybrid.lucidac.front_plane import FrontPlane, SignalGenerator, WaveForm  # noqa: F401

# Backward-compatible alias: old code doing `from front_panel import FrontPanel`
FrontPanel = FrontPlane

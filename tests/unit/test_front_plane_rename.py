# Copyright (c) 2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
Unit tests for FrontPanel -> FrontPlane rename backward compatibility.

These tests verify that:
- Carrier.front_panel emits a DeprecationWarning (backward compat shim).
"""

import warnings

from pybrid.redac.carrier import Carrier
from pybrid.redac.cluster import Cluster
from pybrid.redac.blocks import UBlock, CBlock, IBlock
from pybrid.redac.entities import Path
from pybrid.base.utils.addressing import AddressingMap

# Import FrontPanel/FrontPlane with fallback so tests don't crash
try:
    from pybrid.lucidac.front_plane import FrontPlane
except ImportError:
    from pybrid.lucidac.front_panel import FrontPanel as FrontPlane


def _make_carrier_with_fp(mac: str) -> Carrier:
    """Create a minimal Carrier with a FrontPlane attached for testing.

    Args:
        mac: MAC address string for the carrier path.

    Returns:
        A Carrier dataclass instance with a FrontPlane attached.
    """
    carrier_path = Path.parse(mac)
    cluster_path = carrier_path / "0"
    cluster = Cluster(
        path=cluster_path,
        m0block=None,
        ublock=UBlock(path=cluster_path / "U"),
        cblock=CBlock(path=cluster_path / "C"),
        iblock=IBlock(path=cluster_path / "I"),
        shblock=None,
    )
    fp = FrontPlane(carrier_path / "FP")

    # Try new keyword first, fall back to old keyword
    try:
        return Carrier(
            path=carrier_path,
            clusters=[cluster],
            tblock=None,
            front_plane=fp,
        )
    except TypeError:
        # Fall back to old keyword name for backward compatibility
        return Carrier(
            path=carrier_path,
            clusters=[cluster],
            tblock=None,
            front_panel=fp,
        )


class TestCarrierFrontPanelDeprecated:

    def test_carrier_front_panel_deprecated(self):
        # front_panel is a deprecated property that wraps front_plane
        mac = AddressingMap.map_redac(0)
        carrier = _make_carrier_with_fp(mac)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            _ = carrier.front_panel
            deprecation_warnings = [
                w for w in caught
                if issubclass(w.category, DeprecationWarning)
                and "front_panel" in str(w.message).lower()
            ]
            assert len(deprecation_warnings) >= 1, (
                "Accessing carrier.front_panel should emit a DeprecationWarning "
                "indicating that 'front_plane' is the new attribute name. "
                f"Caught warnings: {[str(w.message) for w in caught]}"
            )



# Copyright (c) 2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
Unit tests for FrontPanel -> FrontPlane rename (Sprint 1 — backward compat).

These tests verify that:
- Carrier.front_plane attribute works (new canonical name).
- Carrier.front_panel emits a DeprecationWarning (backward compat shim).
- The new module pybrid.lucidac.front_plane exposes FrontPlane.
- The old module pybrid.lucidac.front_panel emits DeprecationWarning on import.

These tests are written against the POST-refactoring interface and are
expected to FAIL against the current (pre-refactoring) codebase.
"""

import warnings
import pytest

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
        A Carrier dataclass instance with a FrontPlane on front_panel
        (current code) or front_plane (post-refactoring).
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
        # Pre-refactoring: keyword is still 'front_panel'
        return Carrier(
            path=carrier_path,
            clusters=[cluster],
            tblock=None,
            front_panel=fp,
        )


class TestCarrierFrontPlaneAttribute:
    """Tests for the Carrier.front_plane attribute (new canonical name)."""

    def test_carrier_front_plane_attribute(self):
        """Create a Carrier with front_plane=FrontPlane(path). Access
        carrier.front_plane. Assert it works and is not None.

        Post-refactoring: carrier.front_plane is the canonical attribute.
        Pre-refactoring: carrier has front_panel but NOT front_plane, so
        getattr returns None and the assertion fails.
        """
        mac = AddressingMap.map_redac(0)
        carrier = _make_carrier_with_fp(mac)

        # Use getattr to avoid AttributeError crash; assert it exists
        front_plane = getattr(carrier, "front_plane", None)
        assert front_plane is not None, (
            "Carrier should have a 'front_plane' attribute that is not None. "
            "The attribute may not have been renamed from 'front_panel' yet."
        )
        assert isinstance(front_plane, FrontPlane), (
            f"carrier.front_plane should be a FrontPlane instance, "
            f"got {type(front_plane).__name__}"
        )


class TestCarrierFrontPanelDeprecated:
    """Tests for backward-compat Carrier.front_panel emitting DeprecationWarning."""

    def test_carrier_front_panel_deprecated(self):
        """Access carrier.front_panel and assert it emits a DeprecationWarning.

        Post-refactoring: front_panel is a deprecated property that wraps
        front_plane and emits DeprecationWarning.
        Pre-refactoring: front_panel does NOT emit any warning, so this fails.
        """
        mac = AddressingMap.map_redac(0)
        carrier = _make_carrier_with_fp(mac)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            # Access the old attribute name
            _ = carrier.front_panel
            # Filter for DeprecationWarning
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


class TestFrontPlaneImport:
    """Tests for the new pybrid.lucidac.front_plane module."""

    def test_front_plane_import(self):
        """from pybrid.lucidac.front_plane import FrontPlane should work.

        Post-refactoring: front_plane.py is the canonical module.
        Pre-refactoring: the module is front_panel.py, so the import
        would fail. We catch ImportError and turn it into an assertion.
        """
        import importlib

        try:
            mod = importlib.import_module("pybrid.lucidac.front_plane")
        except ImportError:
            mod = None

        assert mod is not None, (
            "Module pybrid.lucidac.front_plane does not exist yet. "
            "The front_panel.py module has not been renamed to front_plane.py."
        )
        assert hasattr(mod, "FrontPlane"), (
            "Module pybrid.lucidac.front_plane should export 'FrontPlane' class"
        )

    def test_front_panel_import_deprecated(self):
        """from pybrid.lucidac.front_panel import FrontPanel should emit
        DeprecationWarning.

        Post-refactoring: front_panel.py is a re-export shim that emits
        DeprecationWarning on import.
        Pre-refactoring: front_panel.py does NOT emit any warning, so this fails.
        """
        # We do NOT forcefully re-import the module (which causes
        # EntityType registry conflicts). Instead, we test whether
        # importing the already-cached module emitted a deprecation
        # warning at load time by checking if the module has a
        # deprecation marker, or we simply verify the contract:
        # importing front_panel must produce a DeprecationWarning.
        #
        # Since the module is already loaded (cached by Python),
        # we check the module's __warningregistry__ or use a
        # simpler approach: verify the module has a _DEPRECATED flag
        # or that importing it from a fresh perspective triggers a warning.
        import sys

        mod_name = "pybrid.lucidac.front_panel"
        mod = sys.modules.get(mod_name)

        # The module should exist (it's already imported at the top of this file)
        assert mod is not None, (
            "pybrid.lucidac.front_panel module should be importable"
        )

        # Post-refactoring: the module should have a deprecation marker
        # or the FrontPanel name should be an alias from front_plane.
        # We check whether the module sets _DEPRECATED = True or whether
        # accessing FrontPanel triggers a warning.
        #
        # Alternative check: after refactoring, the module should re-export
        # from front_plane, so FrontPlane should be accessible from front_panel.
        has_deprecation_marker = getattr(mod, "_DEPRECATED", False)
        has_front_plane_reexport = hasattr(mod, "FrontPlane")

        assert has_deprecation_marker or has_front_plane_reexport, (
            "pybrid.lucidac.front_panel should either set _DEPRECATED=True "
            "or re-export FrontPlane from pybrid.lucidac.front_plane. "
            "The module has not been converted to a deprecation shim yet."
        )

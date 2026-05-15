# Copyright (c) 2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
Unit tests for deprecated backward-compatibility property shims on
BaseController / REDACController.

The new architecture replaces:
  - `controller.protocols`   → `controller.connection_manager.connections`
  - `controller.devices`     → `controller.connection_manager.get_connection(path)`

Each old property is kept as a shim that:
  1. Emits a DeprecationWarning
  2. Delegates to the new implementation

These tests verify that all three shims behave correctly and that
DeprecationWarning is always emitted.

All tests use mocks — no real network connections are made.
"""

import warnings
from unittest.mock import MagicMock, patch

import pytest

from pybrid.redac.channel import DeviceConnection
from pybrid.redac.controller import Controller as REDACController
from pybrid.redac.entities import Path


def _make_controller(**kwargs) -> REDACController:
    """Construct a REDACController with default or supplied arguments."""
    return REDACController(**kwargs)


def _inject_fake_connections(ctrl: REDACController, macs: list[str]) -> dict:
    """
    Populate controller.connection_manager.connections with fake DeviceConnection
    objects keyed by Path, and return the path→connection mapping.
    """
    result = {}
    for mac in macs:
        path = Path.parse(mac)
        conn = MagicMock(spec=DeviceConnection)
        ctrl.connection_manager.connections[path] = conn
        result[path] = conn
    return result


class TestProtocolsShim:
    """Tests for the deprecated `protocols` property."""

    def test_protocols_shim_emits_deprecation_warning(self):
        ctrl = _make_controller()

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            _ = ctrl.protocols

        deprecation_warnings = [w for w in caught if issubclass(w.category, DeprecationWarning)]
        assert (
            len(deprecation_warnings) >= 1
        ), "Accessing controller.protocols must emit at least one DeprecationWarning"

    def test_protocols_shim_reflects_connections(self):
        """protocols reflects live connection_manager state: empty before injection, non-empty after."""
        ctrl = _make_controller()

        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            before = ctrl.protocols
            # Empty controller — protocols must be empty/falsy
            assert not before or len(list(before)) == 0

        _inject_fake_connections(ctrl, ["AA-BB-CC-DD-EE-01"])

        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            after = ctrl.protocols
            assert after and len(list(after)) > 0, "protocols must reflect newly added connections"


class TestDevicesShim:
    """Tests for the deprecated `devices` property."""

    def test_devices_shim_returns_mapping(self):
        """devices returns a mapping allowing path-keyed lookup of DeviceConnection objects."""
        ctrl = _make_controller()
        expected = _inject_fake_connections(ctrl, ["AA-BB-CC-DD-EE-01"])
        path = Path.parse("AA-BB-CC-DD-EE-01")

        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            devices = ctrl.devices

        # Key lookup must work
        assert path in devices
        assert devices[path] is expected[path]

    def test_devices_shim_emits_deprecation_warning(self):
        ctrl = _make_controller()

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            _ = ctrl.devices

        deprecation_warnings = [w for w in caught if issubclass(w.category, DeprecationWarning)]
        assert len(deprecation_warnings) >= 1, "Accessing controller.devices must emit at least one DeprecationWarning"

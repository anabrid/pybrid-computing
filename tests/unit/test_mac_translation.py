# Copyright (c) 2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
Unit tests for Addressing.remap_virtual_mac() helper.

Sprint 2 introduces a targeted MAC translation helper that replaces all
occurrences of the virtual MAC ``00-00-00-00-00-00`` with a given physical
MAC in a protobuf ``pb.File`` configuration bundle.  This is used by
LucipyWrapper when merging per-device circuits into a single config bundle
before handing them to the controller.

These tests are written TDD-style: they will FAIL until the implementation
of ``Addressing.remap_virtual_mac()`` is added in Sprint 2.
"""

import pytest

import pybrid.base.proto.main_pb2 as pb
from pybrid.base.utils.addressing import Addressing

# ---- Helpers ---------------------------------------------------------------

VIRTUAL_MAC = "00-00-00-00-00-00"
TARGET_MAC = "AB-CD-EF-12-34-56"


def _make_pb_file_with_configs(paths: list[str]) -> pb.File:
    """
    Build a minimal pb.File whose bundle contains one Config per path.

    Each Config gets an EntityId with the given path string.  No actual
    config payload is needed -- the remap helper only touches entity paths.

    Args:
        paths: List of entity path strings (e.g., ``["00-00-00-00-00-00/0/M0"]``).

    Returns:
        A pb.File with a ConfigBundle containing the requested configs.
    """
    configs = []
    for path in paths:
        config = pb.Config(entity=pb.EntityId(path=path))
        configs.append(config)
    return pb.File(bundle=pb.ConfigBundle(configs=configs))


# ---- Tests -----------------------------------------------------------------


class TestRemapVirtualMac:
    """Tests for Addressing.remap_virtual_mac()."""

    def _check_method_exists(self):
        """Guard: fail cleanly if the method is not yet implemented."""
        if not hasattr(Addressing, "remap_virtual_mac"):
            pytest.fail("Addressing.remap_virtual_mac not yet implemented")

    def test_remap_virtual_mac_single_config(self):
        """
        A pb.File with one config whose entity path starts with the virtual
        MAC should have that prefix replaced with the target MAC.
        """
        self._check_method_exists()

        pb_file = _make_pb_file_with_configs([f"{VIRTUAL_MAC}"])
        result = Addressing.remap_virtual_mac(pb_file, TARGET_MAC)

        assert len(result.bundle.configs) == 1
        assert result.bundle.configs[0].entity.path == TARGET_MAC

    def test_remap_virtual_mac_preserves_subpaths(self):
        """
        Subpath components after the MAC prefix must be preserved.

        ``/00-00-00-00-00-00/0/M0`` should become ``/AB-CD-EF-12-34-56/0/M0``.
        """
        self._check_method_exists()

        original_path = f"{VIRTUAL_MAC}/0/M0"
        pb_file = _make_pb_file_with_configs([original_path])
        result = Addressing.remap_virtual_mac(pb_file, TARGET_MAC)

        expected = f"{TARGET_MAC}/0/M0"
        assert result.bundle.configs[0].entity.path == expected, (
            f"Expected '{expected}', got '{result.bundle.configs[0].entity.path}'"
        )

    def test_remap_virtual_mac_skips_global_configs(self):
        """
        Configs with an empty path (global configs outside the entity path
        system) should remain unchanged after remapping.
        """
        self._check_method_exists()

        pb_file = _make_pb_file_with_configs(["", f"{VIRTUAL_MAC}/0/C"])
        result = Addressing.remap_virtual_mac(pb_file, TARGET_MAC)

        # Global config (empty path) must be untouched
        assert result.bundle.configs[0].entity.path == ""
        # Device-scoped config must be remapped
        assert result.bundle.configs[1].entity.path == f"{TARGET_MAC}/0/C"

    def test_remap_virtual_mac_returns_copy(self):
        """
        The method must return a new pb.File, leaving the original untouched.
        """
        self._check_method_exists()

        pb_file = _make_pb_file_with_configs([f"{VIRTUAL_MAC}/0/U"])
        result = Addressing.remap_virtual_mac(pb_file, TARGET_MAC)

        # Original should still have the virtual MAC
        assert pb_file.bundle.configs[0].entity.path == f"{VIRTUAL_MAC}/0/U"
        # Result should have the target MAC
        assert result.bundle.configs[0].entity.path == f"{TARGET_MAC}/0/U"

    def test_remap_virtual_mac_multiple_configs(self):
        """
        All configs with the virtual MAC prefix should be remapped in one call.
        """
        self._check_method_exists()

        paths = [
            f"{VIRTUAL_MAC}/0/M0",
            f"{VIRTUAL_MAC}/0/U",
            f"{VIRTUAL_MAC}/0/C",
            f"{VIRTUAL_MAC}/0/I",
        ]
        pb_file = _make_pb_file_with_configs(paths)
        result = Addressing.remap_virtual_mac(pb_file, TARGET_MAC)

        for config in result.bundle.configs:
            assert config.entity.path.startswith(TARGET_MAC), (
                f"Config path '{config.entity.path}' should start with "
                f"'{TARGET_MAC}'"
            )

# Copyright (c) 2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
Unit tests for addressing deprecation warnings, CLI strict mode,
portable map, and sync-impl flag.

Tests cover:
- Deprecation warnings on ``Addressing.virtual_to_physical()`` and
  ``Addressing.physical_to_virtual()`` (deprecated in favor of CLI-layer
  --strict/--portable-map workflow).
- ``validate_and_map_config()`` strict/non-strict logic extracted from CLI.
- ``parse_sync_impl()`` string-to-enum mapping.
"""

import json
import os
import tempfile
import warnings

import pytest

import pybrid.base.proto.main_pb2 as pb
from pybrid.base.utils.addressing import Addressing, AddressingMap
from pybrid.cli.dac.addressing import validate_and_map_config, parse_sync_impl
from pybrid.redac.carrier import Carrier
from pybrid.redac.cluster import Cluster
from pybrid.redac.blocks import MIntBlock, UBlock, CBlock, IBlock
from pybrid.redac.computer import REDAC
from pybrid.redac.entities import Path
from pybrid.redac.sync import SyncImplementationType


PHYSICAL_MAC_A = "04-E9-E5-14-74-BF"
PHYSICAL_MAC_B = "04-E9-E5-22-33-44"
VIRTUAL_MAC_0 = "00-00-00-00-00-00"
VIRTUAL_MAC_1 = "00-00-00-00-00-01"


def _make_pb_file_with_configs(paths: list[str]) -> pb.File:
    """Build a minimal pb.File whose bundle contains one Config per path."""
    configs = []
    for path in paths:
        config = pb.Config(entity=pb.EntityId(path=path))
        configs.append(config)
    return pb.File(bundle=pb.ConfigBundle(configs=configs))


def _make_minimal_carrier(mac: str) -> Carrier:
    """Create a minimal Carrier with one cluster for testing."""
    carrier_path = Path.parse(mac)
    cluster_path = carrier_path / "0"
    cluster = Cluster(
        path=cluster_path,
        m0block=MIntBlock(path=cluster_path / "M0"),
        ublock=UBlock(path=cluster_path / "U"),
        cblock=CBlock(path=cluster_path / "C"),
        iblock=IBlock(path=cluster_path / "I"),
        shblock=None,
    )
    try:
        return Carrier(
            path=carrier_path,
            clusters=[cluster],
            tblock=None,
            front_plane=None,
        )
    except TypeError:
        return Carrier(
            path=carrier_path,
            clusters=[cluster],
            tblock=None,
            front_panel=None,
        )


def _make_redac(*macs: str) -> REDAC:
    """Build a REDAC computer with one carrier per MAC."""
    carriers = [_make_minimal_carrier(mac) for mac in macs]
    return REDAC(entities=carriers)


class TestAddressingDeprecationWarnings:

    def test_virtual_to_physical_emits_deprecation_warning(self):
        computer = _make_redac(PHYSICAL_MAC_A)
        pb_file = _make_pb_file_with_configs([f"{VIRTUAL_MAC_0}/0/M0"])

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            Addressing.virtual_to_physical(computer, pb_file)

        deprecation_msgs = [
            w for w in caught if issubclass(w.category, DeprecationWarning)
        ]
        assert len(deprecation_msgs) >= 1, (
            "Expected at least one DeprecationWarning from "
            "Addressing.virtual_to_physical()"
        )

    def test_physical_to_virtual_emits_deprecation_warning(self):
        computer = _make_redac(PHYSICAL_MAC_A)
        pb_file = _make_pb_file_with_configs([f"{PHYSICAL_MAC_A}/0/U"])

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            Addressing.physical_to_virtual(computer, pb_file)

        deprecation_msgs = [
            w for w in caught if issubclass(w.category, DeprecationWarning)
        ]
        assert len(deprecation_msgs) >= 1, (
            "Expected at least one DeprecationWarning from "
            "Addressing.physical_to_virtual()"
        )

    def test_remap_virtual_mac_does_not_emit_deprecation_warning(self):
        # remap_virtual_mac is used internally by the Session for per-device
        # circuit translation and must remain warning-free.
        pb_file = _make_pb_file_with_configs([f"{VIRTUAL_MAC_0}/0/I"])

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            Addressing.remap_virtual_mac(pb_file, PHYSICAL_MAC_A)

        deprecation_msgs = [
            w for w in caught if issubclass(w.category, DeprecationWarning)
        ]
        assert len(deprecation_msgs) == 0, (
            "remap_virtual_mac should NOT emit DeprecationWarning, "
            f"but got {len(deprecation_msgs)}"
        )


class TestStrictModeValidation:

    def test_strict_mode_rejects_virtual_addresses(self):
        computer = _make_redac(PHYSICAL_MAC_A)
        pb_file = _make_pb_file_with_configs([f"{VIRTUAL_MAC_0}/0/M0"])

        with pytest.raises(Exception, match="(?i)virtual|strict|portable"):
            validate_and_map_config(
                pb_file=pb_file,
                strict=True,
                portable_map_path=None,
                computer=computer,
                address_map=AddressingMap.map_redac,
            )

    def test_strict_mode_allows_physical_addresses(self):
        computer = _make_redac(PHYSICAL_MAC_A)
        pb_file = _make_pb_file_with_configs([f"{PHYSICAL_MAC_A}/0/U"])

        result = validate_and_map_config(
            pb_file=pb_file,
            strict=True,
            portable_map_path=None,
            computer=computer,
            address_map=AddressingMap.map_redac,
        )

        assert result.bundle.configs[0].entity.path == f"{PHYSICAL_MAC_A}/0/U"

    def test_no_strict_with_portable_map_uses_explicit_mapping(self):
        """With --no-strict and a --portable-map JSON, the explicit mapping is applied without a deprecation warning."""
        computer = _make_redac(PHYSICAL_MAC_A, PHYSICAL_MAC_B)
        pb_file = _make_pb_file_with_configs([
            f"{VIRTUAL_MAC_0}/0/M0",
            f"{VIRTUAL_MAC_1}/0/C",
        ])

        # Write a portable map JSON to a temp file
        portable_map = {
            VIRTUAL_MAC_0: PHYSICAL_MAC_A,
            VIRTUAL_MAC_1: PHYSICAL_MAC_B,
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump(portable_map, f)
            map_path = f.name

        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                result = validate_and_map_config(
                    pb_file=pb_file,
                    strict=False,
                    portable_map_path=map_path,
                    computer=computer,
                    address_map=AddressingMap.map_redac,
                )

            # Verify mapping was applied correctly
            assert result.bundle.configs[0].entity.path == f"{PHYSICAL_MAC_A}/0/M0"
            assert result.bundle.configs[1].entity.path == f"{PHYSICAL_MAC_B}/0/C"

            # No deprecation warning should be emitted when using an explicit map
            deprecation_msgs = [
                w for w in caught if issubclass(w.category, DeprecationWarning)
            ]
            assert len(deprecation_msgs) == 0, (
                "Explicit portable map should NOT trigger DeprecationWarning"
            )
        finally:
            os.unlink(map_path)

    def test_no_strict_without_portable_map_uses_greedy_mapping_with_warning(self):
        """With --no-strict and no portable map, greedy auto-mapping is used and a DeprecationWarning is emitted."""
        computer = _make_redac(PHYSICAL_MAC_A)
        pb_file = _make_pb_file_with_configs([f"{VIRTUAL_MAC_0}/0/I"])

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = validate_and_map_config(
                pb_file=pb_file,
                strict=False,
                portable_map_path=None,
                computer=computer,
                address_map=AddressingMap.map_redac,
            )

        # The mapping should still produce correct results
        assert result.bundle.configs[0].entity.path == f"{PHYSICAL_MAC_A}/0/I"

        # A deprecation warning must be emitted for the greedy auto-mapping
        deprecation_msgs = [
            w for w in caught if issubclass(w.category, DeprecationWarning)
        ]
        assert len(deprecation_msgs) >= 1, (
            "Greedy auto-mapping without portable map should emit "
            "DeprecationWarning"
        )


class TestSyncImplFlag:

    @pytest.mark.parametrize("input_str,expected", [
        ("native", SyncImplementationType.NATIVE),
        ("usbspi", SyncImplementationType.USBSPI),
    ])
    def test_sync_impl_maps_to_enum(self, input_str, expected):
        """sync impl strings map to the corresponding SyncImplementationType enum value."""
        assert parse_sync_impl(input_str) is expected

# Copyright (c) 2022-2025 anabrid GmbH
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
Integration tests for LegacyConfigJSONParser.

Tests verify that legacy JSON configurations can be parsed into the protobuf
format correctly, including carrier extraction, block value parsing, and
error handling for various edge cases.
"""

import pytest

from pybrid.base.utils.json import LegacyConfigJSONParser
from pybrid.base.utils.addressing import AddressingMap
from pybrid.redac.computer import REDAC
from pybrid.redac.carrier import Carrier
from pybrid.redac.cluster import Cluster
from pybrid.redac.blocks import UBlock, CBlock, IBlock, MIntBlock
from pybrid.redac.entities import Path


def make_test_redac_with_mblock(num_carriers: int = 1):
    """
    Create a REDAC computer with MIntBlock for testing legacy parser.

    The legacy parser requires MIntBlock to parse M0 block configurations
    from JSON files like harmonic_legacy.json.

    Args:
        num_carriers: Number of carrier boards to create.

    Returns:
        A REDAC instance with MIntBlock in each cluster.
    """
    carriers = []
    for i in range(num_carriers):
        mac = AddressingMap.map_redac(i)
        carrier_path = Path.parse(mac)

        cluster_path = carrier_path / "0"
        cluster = Cluster(
            path=cluster_path,
            m0block=MIntBlock(path=cluster_path / "M0"),
            ublock=UBlock(path=cluster_path / "U"),
            cblock=CBlock(path=cluster_path / "C"),
            iblock=IBlock(path=cluster_path / "I"),
            shblock=None
        )

        carrier = Carrier(
            path=carrier_path,
            clusters=[cluster],
            tblock=None
        )
        carriers.append(carrier)

    return REDAC(entities=carriers)


class TestExtractCarrier:
    """Tests for LegacyConfigJSONParser.extract_carrier method."""

    def test_valid_carrier_found(self):
        computer = make_test_redac_with_mblock(num_carriers=2)
        carrier_id = AddressingMap.map_redac(0)

        result = LegacyConfigJSONParser.extract_carrier(computer, carrier_id)

        assert result is not None
        assert result.path.to_mac() == carrier_id

    def test_missing_carrier_raises(self):
        computer = make_test_redac_with_mblock(num_carriers=1)
        nonexistent_id = "FF-FF-FF-FF-FF-FF"

        with pytest.raises(Exception) as exc_info:
            LegacyConfigJSONParser.extract_carrier(computer, nonexistent_id)

        assert "Unable to find carrier" in str(exc_info.value)
        assert nonexistent_id in str(exc_info.value)


class TestParseGoldenFile:
    """Tests for parsing the harmonic_legacy.json golden test configuration."""

    def test_harmonic_json_parses(self, harmonic_config):
        computer = make_test_redac_with_mblock(num_carriers=1)

        result = LegacyConfigJSONParser.parse(harmonic_config, computer)

        assert result is not None
        assert result.module is not None
        assert len(result.module.items) > 0

    def test_harmonic_cblock_values(self, harmonic_config):
        """CBlock values from harmonic_legacy.json: elements[0]=-1.0, elements[8]=1.0, others=0.0."""
        computer = make_test_redac_with_mblock(num_carriers=1)
        cluster = computer.carriers[0].clusters[0]

        LegacyConfigJSONParser.parse(harmonic_config, computer)

        # Check the specific values from harmonic_legacy.json
        assert cluster.cblock.elements[0].factor == pytest.approx(-1.0)
        assert cluster.cblock.elements[8].factor == pytest.approx(1.0)

        # Check that other elements are zero
        for i in [1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 12, 13, 14, 15]:
            assert cluster.cblock.elements[i].factor == pytest.approx(0.0), \
                f"Expected element {i} to be 0.0, got {cluster.cblock.elements[i].factor}"

    def test_harmonic_m0block_values(self, harmonic_config):
        """M0Block values from harmonic_legacy.json: element[0] ic=0.0/k=10000, element[1] ic=-0.42/k=10000."""
        computer = make_test_redac_with_mblock(num_carriers=1)
        cluster = computer.carriers[0].clusters[0]

        LegacyConfigJSONParser.parse(harmonic_config, computer)

        # Check the specific values from harmonic_legacy.json
        assert cluster.m0block.elements[0].ic == pytest.approx(0.0)
        assert cluster.m0block.elements[0].k == 10000

        assert cluster.m0block.elements[1].ic == pytest.approx(-0.42)
        assert cluster.m0block.elements[1].k == 10000

        # Check remaining elements have default ic=0.0 and k=10000
        for i in range(2, 8):
            assert cluster.m0block.elements[i].ic == pytest.approx(0.0), \
                f"Expected element {i} ic to be 0.0, got {cluster.m0block.elements[i].ic}"
            assert cluster.m0block.elements[i].k == 10000, \
                f"Expected element {i} k to be 10000, got {cluster.m0block.elements[i].k}"


class TestParseAddressing:
    """Tests for addressing modes during parsing."""

    def test_virtual_to_virtual_succeeds(self, harmonic_config):
        """Parsing succeeds when both config and computer use virtual addresses."""
        computer = make_test_redac_with_mblock(num_carriers=1)

        # Verify the computer uses virtual addresses
        assert computer.carriers[0].path.to_mac() == AddressingMap.map_redac(0)

        result = LegacyConfigJSONParser.parse(harmonic_config, computer)

        assert result is not None
        assert result.module is not None


class TestParseErrorHandling:
    """Tests for error handling during parsing."""

    def test_missing_cluster_skipped(self):
        """Missing cluster configurations are gracefully skipped rather than raising."""
        computer = make_test_redac_with_mblock(num_carriers=1)

        # Config with carrier but no cluster data (no "/0" key)
        config = {
            "00-00-00-00-00-00": {
                "adc_channels": [1]
            }
        }

        # Should not raise - missing clusters are skipped
        result = LegacyConfigJSONParser.parse(config, computer)

        assert result is not None

    def test_empty_config_produces_empty_result(self):
        """Empty config dict produces a valid protobuf File with an empty module."""
        computer = make_test_redac_with_mblock(num_carriers=1)
        config = {}

        result = LegacyConfigJSONParser.parse(config, computer)

        assert result is not None
        assert result.module is not None

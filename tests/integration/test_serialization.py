# Copyright (c) 2022-2025 anabrid GmbH
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
Integration tests for configuration serialization roundtrips.

Tests verify that computer configurations can be serialized to protobuf format
and deserialized back without data loss. Covers REDAC, LUCIDAC, and Simulator
computer types and various block configurations.
"""

import pytest

from pybrid.redac.computer import REDAC
from pybrid.redac.carrier import Carrier, ADCChannel
from pybrid.redac.cluster import Cluster
from pybrid.redac.blocks import UBlock, CBlock, IBlock, MIntBlock
from pybrid.redac.entities import Path
from pybrid.base.utils.addressing import AddressingMap


# =============================================================================
# Helper Functions
# =============================================================================


def make_test_redac_with_mblock(num_carriers: int = 1):
    """
    Create a REDAC computer with MIntBlock for testing integrator serialization.

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


def make_test_lucidac():
    """
    Create a LUCIDAC computer for testing.

    Returns:
        A LUCIDAC instance configured for testing.
    """
    from pybrid.lucidac.computer import LUCIDAC

    mac = AddressingMap.map_redac(0)
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

    return LUCIDAC(entities=[carrier])


def make_test_simulator():
    """
    Create a Simulator computer for testing.

    Returns:
        A Simulator instance configured for testing.
    """
    from pybrid.sim.computer import Simulator

    mac = AddressingMap.map_redac(0)
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

    return Simulator(entities=[carrier])


def serialize_roundtrip(computer):
    """
    Perform a serialization roundtrip for a computer.

    Serializes the computer's configuration to protobuf, creates a fresh
    computer of the same type, and deserializes the config into it.

    Args:
        computer: The configured computer to serialize.

    Returns:
        A new computer with the deserialized configuration.
    """
    # Get the serializer and deserializer types
    serializer_cls = computer.get_serializer_implementation()
    deserializer_cls = computer.get_deserializer_implementation()

    # Serialize the current configuration
    serializer = serializer_cls()
    configs = serializer.serialize(computer)

    # Create a fresh computer with the same structure
    if computer.name == "REDAC":
        fresh_computer = make_test_redac_with_mblock(len(computer.carriers))
    elif computer.name in ("LUCIDAC", "LUCIStack"):
        fresh_computer = make_test_lucidac()
    elif computer.name == "Simulator":
        fresh_computer = make_test_simulator()
    else:
        raise ValueError(f"Unknown computer type: {computer.name}")

    # Deserialize into the fresh computer
    deserializer = deserializer_cls(fresh_computer)
    deserializer.deserialize(configs)

    return fresh_computer


def compare_cblock_elements(original, restored):
    """
    Compare CBlock element configurations.

    Args:
        original: Original CBlock entity.
        restored: Restored CBlock entity.

    Returns:
        True if all elements match, raises AssertionError otherwise.
    """
    assert len(original.elements) == len(restored.elements), \
        f"CBlock element count mismatch: {len(original.elements)} vs {len(restored.elements)}"

    for i, (orig_elem, rest_elem) in enumerate(zip(original.elements, restored.elements)):
        assert orig_elem.computation.factor == pytest.approx(rest_elem.computation.factor, rel=1e-6), \
            f"CBlock element {i} factor mismatch: {orig_elem.computation.factor} vs {rest_elem.computation.factor}"

    return True


def compare_mintblock_elements(original, restored):
    """
    Compare MIntBlock element configurations.

    Args:
        original: Original MIntBlock entity.
        restored: Restored MIntBlock entity.

    Returns:
        True if all elements match, raises AssertionError otherwise.
    """
    assert len(original.elements) == len(restored.elements), \
        f"MIntBlock element count mismatch: {len(original.elements)} vs {len(restored.elements)}"

    for i, (orig_elem, rest_elem) in enumerate(zip(original.elements, restored.elements)):
        assert orig_elem.ic == pytest.approx(rest_elem.ic, rel=1e-6), \
            f"MIntBlock element {i} ic mismatch: {orig_elem.ic} vs {rest_elem.ic}"
        assert orig_elem.k == rest_elem.k, \
            f"MIntBlock element {i} k mismatch: {orig_elem.k} vs {rest_elem.k}"

    # Check limiters
    assert original.limiters == restored.limiters, \
        f"MIntBlock limiters mismatch: {original.limiters} vs {restored.limiters}"

    return True


def compare_adc_channels(original, restored):
    """
    Compare ADC channel configurations.

    Args:
        original: Original Carrier entity.
        restored: Restored Carrier entity.

    Returns:
        True if all ADC channels match, raises AssertionError otherwise.
    """
    assert len(original.adc_config) == len(restored.adc_config), \
        f"ADC channel count mismatch: {len(original.adc_config)} vs {len(restored.adc_config)}"

    for i, (orig_ch, rest_ch) in enumerate(zip(original.adc_config, restored.adc_config)):
        assert orig_ch.index == rest_ch.index, \
            f"ADC channel {i} index mismatch: {orig_ch.index} vs {rest_ch.index}"
        assert orig_ch.gain == pytest.approx(rest_ch.gain, rel=1e-6), \
            f"ADC channel {i} gain mismatch: {orig_ch.gain} vs {rest_ch.gain}"
        assert orig_ch.offset == pytest.approx(rest_ch.offset, rel=1e-6), \
            f"ADC channel {i} offset mismatch: {orig_ch.offset} vs {rest_ch.offset}"

    return True


# =============================================================================
# Test Classes
# =============================================================================


class TestEmptyConfigRoundtrip:
    """Test roundtrip serialization of empty/default configurations."""

    @pytest.mark.parametrize("computer_factory,computer_name", [
        (make_test_redac_with_mblock, "REDAC"),
        (make_test_lucidac, "LUCIStack"),
        (make_test_simulator, "Simulator"),
    ])
    def test_empty_config_roundtrip(self, computer_factory, computer_name):
        """
        Test that an empty configuration survives roundtrip serialization.

        The default state of a newly created computer should be preserved
        after serialization and deserialization.
        """
        computer = computer_factory() if computer_name == "REDAC" else computer_factory()
        assert computer.name == computer_name

        # Perform roundtrip
        restored = serialize_roundtrip(computer)

        # Verify computer type preserved
        assert restored.name == computer_name

        # Verify structure preserved
        assert len(restored.carriers) == len(computer.carriers)
        for orig_carrier, rest_carrier in zip(computer.carriers, restored.carriers):
            assert len(orig_carrier.clusters) == len(rest_carrier.clusters)


class TestCBlockElementsPreserved:
    """Test that CBlock coefficient elements survive roundtrip."""

    def test_cblock_single_coefficient(self):
        """Test roundtrip with a single modified coefficient."""
        computer = make_test_redac_with_mblock()
        cluster = computer.carriers[0].clusters[0]

        # Set a single coefficient
        cluster.cblock.elements[0].computation.factor = 0.5

        restored = serialize_roundtrip(computer)
        restored_cluster = restored.carriers[0].clusters[0]

        compare_cblock_elements(cluster.cblock, restored_cluster.cblock)

    def test_cblock_multiple_coefficients(self):
        """Test roundtrip with multiple modified coefficients."""
        computer = make_test_redac_with_mblock()
        cluster = computer.carriers[0].clusters[0]

        # Set multiple coefficients with various values
        test_values = [0.1, -0.5, 0.75, -1.0, 0.0, 0.33, -0.25, 0.99]
        for i, val in enumerate(test_values):
            cluster.cblock.elements[i].computation.factor = val

        restored = serialize_roundtrip(computer)
        restored_cluster = restored.carriers[0].clusters[0]

        compare_cblock_elements(cluster.cblock, restored_cluster.cblock)

    def test_cblock_all_coefficients(self):
        """Test roundtrip with all 32 coefficients set."""
        computer = make_test_redac_with_mblock()
        cluster = computer.carriers[0].clusters[0]

        # Set all 32 coefficients
        for i in range(32):
            factor = (i - 16) / 16.0  # Values from -1.0 to ~0.94
            cluster.cblock.elements[i].computation.factor = factor

        restored = serialize_roundtrip(computer)
        restored_cluster = restored.carriers[0].clusters[0]

        compare_cblock_elements(cluster.cblock, restored_cluster.cblock)

    def test_cblock_boundary_values(self):
        """Test roundtrip with boundary coefficient values."""
        computer = make_test_redac_with_mblock()
        cluster = computer.carriers[0].clusters[0]

        # Test boundary values: -1.0, 0.0, 1.0
        cluster.cblock.elements[0].computation.factor = -1.0
        cluster.cblock.elements[1].computation.factor = 0.0
        cluster.cblock.elements[2].computation.factor = 1.0

        restored = serialize_roundtrip(computer)
        restored_cluster = restored.carriers[0].clusters[0]

        compare_cblock_elements(cluster.cblock, restored_cluster.cblock)


class TestMIntBlockElementsPreserved:
    """Test that MIntBlock integrator elements survive roundtrip."""

    def test_mintblock_single_integrator(self):
        """Test roundtrip with a single modified integrator."""
        computer = make_test_redac_with_mblock()
        cluster = computer.carriers[0].clusters[0]

        # Set a single integrator
        cluster.m0block.elements[0].ic = 0.5
        cluster.m0block.elements[0].k = 100

        restored = serialize_roundtrip(computer)
        restored_cluster = restored.carriers[0].clusters[0]

        compare_mintblock_elements(cluster.m0block, restored_cluster.m0block)

    def test_mintblock_multiple_integrators(self):
        """Test roundtrip with multiple modified integrators."""
        computer = make_test_redac_with_mblock()
        cluster = computer.carriers[0].clusters[0]

        # Set multiple integrators with various IC values and k values
        test_configs = [
            (0.0, 10000),
            (0.5, 100),
            (-0.5, 10000),
            (1.0, 100),
            (-1.0, 10000),
            (0.25, 100),
            (-0.75, 10000),
            (0.33, 100),
        ]
        for i, (ic, k) in enumerate(test_configs):
            cluster.m0block.elements[i].ic = ic
            cluster.m0block.elements[i].k = k

        restored = serialize_roundtrip(computer)
        restored_cluster = restored.carriers[0].clusters[0]

        compare_mintblock_elements(cluster.m0block, restored_cluster.m0block)

    def test_mintblock_limiters(self):
        """Test roundtrip with limiter configuration."""
        computer = make_test_redac_with_mblock()
        cluster = computer.carriers[0].clusters[0]

        # Set limiters
        cluster.m0block.limiters = [True, False, True, False, True, True, False, False]

        restored = serialize_roundtrip(computer)
        restored_cluster = restored.carriers[0].clusters[0]

        compare_mintblock_elements(cluster.m0block, restored_cluster.m0block)

    def test_mintblock_boundary_ic_values(self):
        """Test roundtrip with boundary IC values."""
        computer = make_test_redac_with_mblock()
        cluster = computer.carriers[0].clusters[0]

        # Test boundary IC values: -1.0, 0.0, 1.0
        cluster.m0block.elements[0].ic = -1.0
        cluster.m0block.elements[1].ic = 0.0
        cluster.m0block.elements[2].ic = 1.0

        restored = serialize_roundtrip(computer)
        restored_cluster = restored.carriers[0].clusters[0]

        compare_mintblock_elements(cluster.m0block, restored_cluster.m0block)


class TestADCChannelsPreserved:
    """Test that ADC channel configurations survive roundtrip."""

    def test_adc_single_channel(self):
        """Test roundtrip with a single ADC channel."""
        computer = make_test_redac_with_mblock()
        carrier = computer.carriers[0]

        # Add a single ADC channel
        carrier.adc_config = [ADCChannel(index=0, gain=1.0, offset=0.0)]

        restored = serialize_roundtrip(computer)
        restored_carrier = restored.carriers[0]

        compare_adc_channels(carrier, restored_carrier)

    def test_adc_multiple_channels(self):
        """Test roundtrip with multiple ADC channels."""
        computer = make_test_redac_with_mblock()
        carrier = computer.carriers[0]

        # Add multiple ADC channels with various configurations
        carrier.adc_config = [
            ADCChannel(index=0, gain=1.0, offset=0.0),
            ADCChannel(index=1, gain=2.0, offset=0.5),
            ADCChannel(index=2, gain=0.5, offset=-0.25),
            ADCChannel(index=3, gain=1.5, offset=0.1),
        ]

        restored = serialize_roundtrip(computer)
        restored_carrier = restored.carriers[0]

        compare_adc_channels(carrier, restored_carrier)

    def test_adc_with_gain_offset(self):
        """Test roundtrip with non-trivial gain and offset values."""
        computer = make_test_redac_with_mblock()
        carrier = computer.carriers[0]

        # Add ADC channels with specific gain and offset values
        carrier.adc_config = [
            ADCChannel(index=5, gain=10.0, offset=100.0),
            ADCChannel(index=10, gain=0.1, offset=-50.0),
        ]

        restored = serialize_roundtrip(computer)
        restored_carrier = restored.carriers[0]

        compare_adc_channels(carrier, restored_carrier)

    def test_adc_empty_config(self):
        """Test roundtrip with empty ADC configuration."""
        computer = make_test_redac_with_mblock()
        carrier = computer.carriers[0]

        # Ensure ADC config is empty
        carrier.adc_config = []

        restored = serialize_roundtrip(computer)
        restored_carrier = restored.carriers[0]

        # Empty ADC config should remain empty
        assert len(restored_carrier.adc_config) == 0


class TestUBlockPreserved:
    """Test that UBlock configurations survive roundtrip."""

    def test_ublock_connections(self):
        """Test roundtrip with UBlock connections."""
        computer = make_test_redac_with_mblock()
        cluster = computer.carriers[0].clusters[0]

        # Set some connections
        cluster.ublock.outputs[0] = 5
        cluster.ublock.outputs[10] = 3
        cluster.ublock.outputs[31] = 15

        restored = serialize_roundtrip(computer)
        restored_cluster = restored.carriers[0].clusters[0]

        # Check connections preserved
        assert cluster.ublock.outputs[0] == restored_cluster.ublock.outputs[0]
        assert cluster.ublock.outputs[10] == restored_cluster.ublock.outputs[10]
        assert cluster.ublock.outputs[31] == restored_cluster.ublock.outputs[31]

    def test_ublock_constant_positive_one(self):
        """Test roundtrip with positive constant value +1.0."""
        computer = make_test_redac_with_mblock()
        cluster = computer.carriers[0].clusters[0]

        cluster.ublock.constant = 1.0
        cluster.ublock.outputs[0] = 15  # Connect constant input

        restored = serialize_roundtrip(computer)
        restored_cluster = restored.carriers[0].clusters[0]

        assert restored_cluster.ublock.constant == 1.0

    def test_ublock_constant_positive_tenth(self):
        """Test roundtrip with positive constant value +0.1."""
        computer = make_test_redac_with_mblock()
        cluster = computer.carriers[0].clusters[0]

        cluster.ublock.constant = 0.1
        cluster.ublock.outputs[0] = 15

        restored = serialize_roundtrip(computer)
        restored_cluster = restored.carriers[0].clusters[0]

        assert restored_cluster.ublock.constant == 0.1

    def test_ublock_constant_negative_tenth(self):
        """Test roundtrip with negative constant value -0.1."""
        computer = make_test_redac_with_mblock()
        cluster = computer.carriers[0].clusters[0]

        cluster.ublock.constant = -0.1
        cluster.ublock.outputs[0] = 15

        restored = serialize_roundtrip(computer)
        restored_cluster = restored.carriers[0].clusters[0]

        assert restored_cluster.ublock.constant == -0.1

    def test_ublock_constant_ground(self):
        """Test roundtrip with ground (disabled) constant."""
        computer = make_test_redac_with_mblock()
        cluster = computer.carriers[0].clusters[0]

        cluster.ublock.constant = False
        cluster.ublock.outputs[0] = 5

        restored = serialize_roundtrip(computer)
        restored_cluster = restored.carriers[0].clusters[0]

        assert restored_cluster.ublock.constant == False


class TestIBlockPreserved:
    """Test that IBlock configurations survive roundtrip."""

    def test_iblock_connections(self):
        """Test roundtrip with IBlock sum connections."""
        computer = make_test_redac_with_mblock()
        cluster = computer.carriers[0].clusters[0]

        # Set some sum connections
        cluster.iblock.outputs[0] = {0, 1, 2}
        cluster.iblock.outputs[5] = {10, 15}
        cluster.iblock.outputs[15] = {31}

        restored = serialize_roundtrip(computer)
        restored_cluster = restored.carriers[0].clusters[0]

        # Check connections preserved
        assert cluster.iblock.outputs[0] == restored_cluster.iblock.outputs[0]
        assert cluster.iblock.outputs[5] == restored_cluster.iblock.outputs[5]
        assert cluster.iblock.outputs[15] == restored_cluster.iblock.outputs[15]

    def test_iblock_upscaling(self):
        """Test roundtrip with IBlock upscaling configuration."""
        computer = make_test_redac_with_mblock()
        cluster = computer.carriers[0].clusters[0]

        # Set upscaling and connections
        cluster.iblock.outputs[0] = {0}
        cluster.iblock.upscaling[0] = True
        cluster.iblock.upscaling[10] = True
        cluster.iblock.upscaling[31] = True

        restored = serialize_roundtrip(computer)
        restored_cluster = restored.carriers[0].clusters[0]

        # Check upscaling preserved
        assert restored_cluster.iblock.upscaling[0] == True
        assert restored_cluster.iblock.upscaling[10] == True
        assert restored_cluster.iblock.upscaling[31] == True


class TestComplexConfigRoundtrip:
    """Test roundtrip with complex multi-block configurations."""

    def test_full_cluster_configuration(self):
        """Test roundtrip with a fully configured cluster."""
        computer = make_test_redac_with_mblock()
        cluster = computer.carriers[0].clusters[0]
        carrier = computer.carriers[0]

        # Configure all blocks
        # UBlock: set connections and constant
        cluster.ublock.constant = 1.0
        cluster.ublock.outputs[0] = 0
        cluster.ublock.outputs[1] = 1
        cluster.ublock.outputs[15] = 15

        # CBlock: set coefficients
        cluster.cblock.elements[0].computation.factor = 0.5
        cluster.cblock.elements[1].computation.factor = -0.25
        cluster.cblock.elements[15].computation.factor = 0.75

        # IBlock: set connections and upscaling
        cluster.iblock.outputs[0] = {0}
        cluster.iblock.outputs[1] = {1, 2}
        cluster.iblock.upscaling[0] = True

        # MIntBlock: set integrators
        cluster.m0block.elements[0].ic = 0.5
        cluster.m0block.elements[0].k = 100
        cluster.m0block.limiters[0] = True

        # ADC channels
        carrier.adc_config = [
            ADCChannel(index=0, gain=1.0, offset=0.0),
            ADCChannel(index=8, gain=2.0, offset=0.5),
        ]

        # Perform roundtrip
        restored = serialize_roundtrip(computer)
        restored_cluster = restored.carriers[0].clusters[0]
        restored_carrier = restored.carriers[0]

        # Verify all configurations preserved
        assert restored_cluster.ublock.constant == 1.0
        assert restored_cluster.ublock.outputs[0] == 0
        assert restored_cluster.ublock.outputs[1] == 1
        assert restored_cluster.ublock.outputs[15] == 15

        compare_cblock_elements(cluster.cblock, restored_cluster.cblock)

        assert restored_cluster.iblock.outputs[0] == {0}
        assert restored_cluster.iblock.outputs[1] == {1, 2}
        assert restored_cluster.iblock.upscaling[0] == True

        compare_mintblock_elements(cluster.m0block, restored_cluster.m0block)

        compare_adc_channels(carrier, restored_carrier)

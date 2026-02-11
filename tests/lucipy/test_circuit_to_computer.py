# Copyright (c) 2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
Unit tests for Circuit.to_computer() export functionality.

These tests verify that:
- to_computer() returns a valid LUCIDAC instance
- A harmonic oscillator circuit produces correct U/C/I state
- to_computer() emits a warning about manual changes
- copy.deepcopy() works on LUCIDAC objects (needed by connection pool)

Written as TDD tests before the Circuit class rewrite.
"""

import copy
import warnings
import pytest

from pybrid.lucipy.circuits import Circuit
from pybrid.lucidac.computer import LUCIDAC


class TestToComputer:
    """Tests for Circuit.to_computer() method."""

    def test_to_computer_returns_lucidac(self):
        """to_computer() must return a LUCIDAC instance."""
        circuit = Circuit()
        result = circuit.to_computer()

        assert isinstance(result, LUCIDAC), (
            f"to_computer() must return a LUCIDAC instance, got {type(result)}"
        )

    def test_to_computer_harmonic_oscillator(self):
        """
        Build a harmonic oscillator (2 integrators in feedback loop):
            i0' = -i1     (weight -1.0)
            i1' =  i0     (weight  1.0)
        Verify U/C/I state is correct on the pybrid object.
        """
        circuit = Circuit()
        i0 = circuit.int(ic=1.0)
        i1 = circuit.int(ic=0.0)

        # i0 feeds into i1 with weight +1.0
        circuit.connect(i0, i1, weight=1.0)
        # i1 feeds back into i0 with weight -1.0
        circuit.connect(i1, i0, weight=-1.0)

        lucidac = circuit.to_computer()
        cluster = lucidac.entities[0].clusters[0]

        # Verify IC values on MIntBlock
        assert cluster.m0block.elements[i0.id].computation.ic == pytest.approx(1.0), (
            f"Integrator {i0.id} IC should be 1.0"
        )
        assert cluster.m0block.elements[i1.id].computation.ic == pytest.approx(0.0), (
            f"Integrator {i1.id} IC should be 0.0"
        )

        # Find lanes for connection i0 -> i1 (weight +1.0)
        lanes_i0_to_i1 = [
            lane for lane in range(24)
            if cluster.ublock.outputs[lane] == i0.lane
        ]
        assert len(lanes_i0_to_i1) >= 1, (
            "Expected at least 1 lane connecting i0 -> i1"
        )

        # Verify the CBlock coefficient for i0->i1 connection
        for lane in lanes_i0_to_i1:
            c_factor = cluster.cblock.elements[lane].computation.factor
            upscaled = cluster.iblock.upscaling[lane]
            effective = c_factor * 8 if upscaled else c_factor
            assert effective == pytest.approx(1.0), (
                f"Coefficient for i0->i1 at lane {lane} should be 1.0, "
                f"got effective={effective}"
            )
            # IBlock should route to i1
            assert lane in cluster.iblock.outputs[i1.lane], (
                f"IBlock outputs[{i1.lane}] should contain lane {lane} "
                f"for i0->i1 connection"
            )

        # Find lanes for connection i1 -> i0 (weight -1.0)
        lanes_i1_to_i0 = [
            lane for lane in range(24)
            if cluster.ublock.outputs[lane] == i1.lane
        ]
        assert len(lanes_i1_to_i0) >= 1, (
            "Expected at least 1 lane connecting i1 -> i0"
        )

        # Verify the CBlock coefficient for i1->i0 connection
        for lane in lanes_i1_to_i0:
            c_factor = cluster.cblock.elements[lane].computation.factor
            upscaled = cluster.iblock.upscaling[lane]
            effective = c_factor * 8 if upscaled else c_factor
            assert effective == pytest.approx(-1.0), (
                f"Coefficient for i1->i0 at lane {lane} should be -1.0, "
                f"got effective={effective}"
            )
            # IBlock should route to i0
            assert lane in cluster.iblock.outputs[i0.lane], (
                f"IBlock outputs[{i0.lane}] should contain lane {lane} "
                f"for i1->i0 connection"
            )

    def test_to_computer_warns_on_manual_changes(self):
        """to_computer() must emit a warning about manual changes."""
        circuit = Circuit()

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            circuit.to_computer()

            # Filter for any warning emitted during the call
            relevant_warnings = [
                x for x in w
                if issubclass(x.category, (UserWarning, DeprecationWarning))
            ]
            assert len(relevant_warnings) >= 1, (
                "to_computer() should emit a warning about manual changes, "
                f"but no relevant warnings were captured. All warnings: {w}"
            )


class TestDeepCopyLUCIDAC:
    """Tests for copy.deepcopy() support on LUCIDAC objects."""

    def test_deepcopy_lucidac(self):
        """
        copy.deepcopy(LUCIDAC()) must succeed and produce independent objects.
        Modifying the copy must not affect the original.
        """
        # Create a LUCIDAC through Circuit to get a fully populated one
        circuit = Circuit()
        i0 = circuit.int(ic=0.5)
        i1 = circuit.int(ic=-0.3)
        circuit.connect(i0, i1, weight=1.0)

        original = circuit.to_computer()
        cloned = copy.deepcopy(original)

        # Basic type check
        assert isinstance(cloned, LUCIDAC), (
            "deepcopy of LUCIDAC must produce a LUCIDAC instance"
        )

        # Verify independence: modify the clone and check the original is unchanged
        original_cluster = original.entities[0].clusters[0]
        cloned_cluster = cloned.entities[0].clusters[0]

        # Capture original IC
        original_ic = original_cluster.m0block.elements[0].computation.ic

        # Modify the clone
        cloned_cluster.m0block.elements[0].computation.ic = 0.99

        # Original should be unchanged
        assert original_cluster.m0block.elements[0].computation.ic == pytest.approx(original_ic), (
            "Modifying deepcopy should not affect the original LUCIDAC object"
        )

        # Verify UBlock independence
        original_u = original_cluster.ublock.outputs[:]
        cloned_cluster.ublock.outputs[0] = 99
        assert original_cluster.ublock.outputs == original_u, (
            "Modifying UBlock on deepcopy should not affect the original"
        )

# Copyright (c) 2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
Unit tests for Circuit.measure() ADC channel assignment.

These tests verify that measure() correctly:
- Greedily assigns ADC channels starting from 0
- Supports explicit channel specification
- Raises ValueError on ADC channel exhaustion (max 8 channels)

Written as TDD tests before the Circuit class rewrite.
"""

import pytest

from pybrid.lucipy.circuits import Circuit


class TestMeasure:
    """Tests for Circuit.measure() ADC channel assignment (deprecated API)."""

    def test_measure_greedy(self):
        """
        Greedy assignment: measure(i0) gets channel 0, measure(i1) gets channel 1.
        """
        circuit = Circuit()
        i0 = circuit.int()
        i1 = circuit.int()

        with pytest.warns(DeprecationWarning):
            ch0 = circuit.measure(i0)
            ch1 = circuit.measure(i1)

        assert ch0 == 0, (
            f"First greedy measure() should assign channel 0, got {ch0}"
        )
        assert ch1 == 1, (
            f"Second greedy measure() should assign channel 1, got {ch1}"
        )

    def test_measure_explicit_channel(self):
        """
        Explicit channel: measure(i0, adc_channel=5) assigns channel 5.
        """
        circuit = Circuit()
        i0 = circuit.int()

        with pytest.warns(DeprecationWarning):
            ch = circuit.measure(i0, adc_channel=5)

        assert ch == 5, (
            f"Explicit measure(adc_channel=5) should return 5, got {ch}"
        )

    def test_measure_overflow(self):
        """
        The 9th measure() call must raise ValueError (only 8 ADC channels).
        """
        circuit = Circuit()
        integrators = [circuit.int() for _ in range(8)]

        # Assign all 8 ADC channels
        with pytest.warns(DeprecationWarning):
            for i, integrator in enumerate(integrators):
                circuit.measure(integrator)

        # The 9th allocation should fail — use a multiplier as the 9th source
        # since all 8 integrators are already allocated.
        m0 = circuit.mul()
        with pytest.raises(ValueError, match="(?i)adc|channel|measure|free|occupied"):
            with pytest.warns(DeprecationWarning):
                circuit.measure(m0)

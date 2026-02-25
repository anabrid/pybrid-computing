# Copyright (c) 2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
Unit tests for Circuit.measure() ADC channel assignment.

These tests verify that measure() correctly raises ValueError on ADC channel
exhaustion (max 8 channels).
"""

import pytest

from pybrid.lucipy.circuits import Circuit


class TestMeasure:
    """Tests for Circuit.measure() ADC channel assignment (deprecated API)."""

    def test_measure_overflow(self):
        """The 9th measure() call must raise ValueError (only 8 ADC channels)."""
        circuit = Circuit("AA-BB-CC-DD-EE-FF")
        integrators = [circuit.int() for _ in range(8)]

        with pytest.warns(DeprecationWarning):
            for i, integrator in enumerate(integrators):
                circuit.measure(integrator)

        m0 = circuit.mul()
        with pytest.raises(ValueError, match="(?i)adc|channel|measure|free|occupied"):
            with pytest.warns(DeprecationWarning):
                circuit.measure(m0)

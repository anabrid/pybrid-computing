# Copyright (c) 2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
Unit tests for Circuit.probe() ADC channel assignment.

These tests verify that probe() correctly raises ValueError on ADC channel
exhaustion (max 8 channels).
"""

import pytest

from pybrid.lucipy.circuits import Circuit


class TestProbe:
    """Tests for Circuit.probe() ADC channel assignment."""

    def test_probe_overflow(self):
        """The 9th probe() call must raise ValueError (only 8 ADC channels)."""
        circuit = Circuit("AA-BB-CC-DD-EE-FF")
        integrators = [circuit.int() for _ in range(8)]

        for integrator in integrators:
            circuit.probe(integrator)

        m0 = circuit.mul()
        with pytest.raises(ValueError, match="(?i)adc|channel|probe|free|occupied"):
            circuit.probe(m0)

#!/usr/bin/env python3

# Copyright (c) 2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
Tests for Circuit.probe() API.

Tests the probe() method for ADC channel assignment.
"""

import pytest

from pybrid.lucipy.circuits import Circuit


class TestProbeADC:
    """Test probe() ADC assignment mode."""

    def test_probe_adc_assigns_channel(self):
        circuit = Circuit("AA-BB-CC-DD-EE-FF")
        integrator = circuit.int()

        channel = circuit.probe(integrator, adc_channel=0)

        assert channel == 0
        assert circuit._carrier.adc_config[0].index == integrator.lane

    def test_probe_adc_greedy(self):
        circuit = Circuit("AA-BB-CC-DD-EE-FF")
        int0 = circuit.int()
        int1 = circuit.int()

        channel0 = circuit.probe(int0)
        channel1 = circuit.probe(int1)

        assert channel0 == 0
        assert channel1 == 1
        assert circuit._carrier.adc_config[0].index == int0.lane
        assert circuit._carrier.adc_config[1].index == int1.lane

    def test_probe_adc_raises_on_occupied_channel(self):
        circuit = Circuit("AA-BB-CC-DD-EE-FF")
        int0 = circuit.int()
        int1 = circuit.int()

        circuit.probe(int0, adc_channel=0)

        with pytest.raises(ValueError, match="ADC channel 0 is already occupied"):
            circuit.probe(int1, adc_channel=0)


class TestProbeAutoAssignsProbeIndex:
    """Test that probe() auto-assigns sequential probe indices starting from 0."""

    def test_probe_adc_assigns_sequential_probe_index(self):
        circuit = Circuit("AA-BB-CC-DD-EE-FF")
        int0 = circuit.int()

        circuit.probe(int0)

        adc = circuit._carrier.adc_config[0]
        assert adc.probe == 0

    def test_probe_adc_with_explicit_channel_still_assigns_probe(self):
        circuit = Circuit("AA-BB-CC-DD-EE-FF")
        int0 = circuit.int()

        circuit.probe(int0, adc_channel=5)

        adc = circuit._carrier.adc_config[5]
        assert adc.probe == 0

    def test_multiple_probes_incrementing(self):
        circuit = Circuit("AA-BB-CC-DD-EE-FF")
        int0 = circuit.int()
        int1 = circuit.int()
        int2 = circuit.int()

        circuit.probe(int0)
        circuit.probe(int1)
        circuit.probe(int2)

        assert circuit._carrier.adc_config[0].probe == 0
        assert circuit._carrier.adc_config[1].probe == 1
        assert circuit._carrier.adc_config[2].probe == 2

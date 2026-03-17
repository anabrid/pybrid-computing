#!/usr/bin/env python3

# Copyright (c) 2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
Tests for Circuit.probe() / measure() API.

Tests the unified probe() method with signature-based dispatch:
- probe(source, adc_channel=N) → ADC assignment (new canonical)
- probe(source, front_port=N) → ACL_OUT (deprecated, signature detection)
- measure(source, ...) → deprecated alias for probe()
"""

import pytest

from pybrid.lucipy.circuits import Circuit


class TestProbeADC:
    """Test probe() ADC assignment mode (new canonical behavior)."""

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


class TestProbeFrontPortDeprecated:
    """Test probe(front_port=...) deprecated ACL_OUT mode."""

    def test_probe_front_port_deprecated(self):
        circuit = Circuit("AA-BB-CC-DD-EE-FF")
        integrator = circuit.int()

        with pytest.warns(DeprecationWarning, match="probe\\(front_port=...\\) is deprecated"):
            output = circuit.probe(integrator, front_port=0)

        # Verify it allocated an ACL_OUT port
        assert output.port == 0
        assert output.lane == 24
        assert circuit._acl_out_used[0] is True

        # Verify the connection was made (UBlock output → ACL lane)
        lucidac = circuit._lucidac
        carrier = lucidac.entities[0]
        cluster = carrier.clusters[0]
        assert cluster.ublock.outputs[24] == integrator.lane
        assert cluster.cblock.elements[24].computation.factor == 1.0

    def test_probe_front_port_with_weight(self):
        circuit = Circuit("AA-BB-CC-DD-EE-FF")
        integrator = circuit.int()

        with pytest.warns(DeprecationWarning):
            output = circuit.probe(integrator, front_port=1, weight=0.5)

        assert output.port == 1
        lucidac = circuit._lucidac
        carrier = lucidac.entities[0]
        cluster = carrier.clusters[0]
        assert cluster.cblock.elements[25].computation.factor == 0.5


class TestMeasureDeprecated:
    """Test measure() deprecated alias."""

    def test_measure_deprecated(self):
        circuit = Circuit("AA-BB-CC-DD-EE-FF")
        integrator = circuit.int()

        with pytest.warns(DeprecationWarning, match="measure\\(\\) is deprecated"):
            channel = circuit.measure(integrator)

        assert channel == 0
        assert circuit._carrier.adc_config[0].index == integrator.lane

    def test_measure_with_adc_channel(self):
        circuit = Circuit("AA-BB-CC-DD-EE-FF")
        integrator = circuit.int()

        with pytest.warns(DeprecationWarning):
            channel = circuit.measure(integrator, adc_channel=2)

        assert channel == 2
        assert circuit._carrier.adc_config[2].index == integrator.lane


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


class TestFrontPanelPropertyDeprecated:
    """Test front_panel property deprecation (kept for sine-extra.py)."""

    def test_front_panel_property_deprecated(self):
        circuit = Circuit("AA-BB-CC-DD-EE-FF")

        with pytest.warns(DeprecationWarning, match="front_panel property is deprecated"):
            front_panel = circuit.front_panel

        # Verify it returns the carrier's front_plane
        assert front_panel is circuit._carrier.front_plane

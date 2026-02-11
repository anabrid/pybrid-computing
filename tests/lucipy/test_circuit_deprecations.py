# Copyright (c) 2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
Unit tests for deprecation shims in the new Circuit class.

These tests verify that the deprecated API methods (probe, front_input,
front_panel property) emit DeprecationWarning while still functioning
correctly, ensuring backward compatibility during the migration.

Written as TDD tests before the Circuit class rewrite.
"""

import pytest
import warnings

from pybrid.lucipy.circuits import Circuit, Output, Input


class TestDeprecationShims:
    """Tests for deprecated Circuit methods that must still work."""

    def test_probe_front_port_warns_and_works(self):
        """
        circuit.probe(i0, front_port=0) must emit DeprecationWarning and
        successfully allocate an Output element and connect it.

        Note: probe(source) without front_port is now the canonical ADC
        assignment (Sprint 3). The old ACL_OUT behavior requires front_port.
        """
        circuit = Circuit()
        i0 = circuit.int()

        with pytest.warns(DeprecationWarning):
            result = circuit.probe(i0, front_port=0)

        # probe(front_port=...) should still produce a working connection.
        lucidac = circuit.to_computer()
        cluster = lucidac.entities[0].clusters[0]

        # Verify that at least one ACL lane (24-31) has a U-block
        # output pointing to i0's lane, confirming the probe connection.
        acl_lanes_with_source = [
            lane for lane in range(24, 32)
            if cluster.ublock.outputs[lane] == i0.lane
        ]
        assert len(acl_lanes_with_source) >= 1, (
            "probe(front_port=...) should create a connection from the source to an "
            "ACL_OUT lane, but no such connection found in U-block"
        )

    def test_front_input_warns_and_works(self):
        """
        circuit.front_input(0) must emit DeprecationWarning and allocate
        an Input element for port 0.
        """
        circuit = Circuit()

        with pytest.warns(DeprecationWarning):
            result = circuit.front_input(0)

        # The result should be an Input instance or at least the call
        # should not raise. Verify that an input was allocated.
        assert isinstance(result, Input), (
            f"front_input() should return an Input instance, got {type(result)}"
        )
        assert result.port == 0, (
            f"front_input(0) should allocate port 0, got port {result.port}"
        )

    def test_front_panel_property_warns(self):
        """
        Accessing circuit.front_panel must emit DeprecationWarning.
        """
        circuit = Circuit()

        with pytest.warns(DeprecationWarning):
            fp = circuit.front_panel

        # The property should return the signal generator from the
        # internal LUCIDAC object (or at least not be None).
        assert fp is not None, (
            "front_panel property should return a non-None value "
            "(the signal generator from the internal LUCIDAC)"
        )

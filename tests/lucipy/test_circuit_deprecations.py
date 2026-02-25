# Copyright (c) 2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
Unit tests for deprecation shims in the new Circuit class.

These tests verify that the deprecated API methods (front_input) emit
DeprecationWarning while still functioning correctly, ensuring backward
compatibility during the migration.
"""

import pytest

from pybrid.lucipy.circuits import Circuit, Input


class TestDeprecationShims:
    """Tests for deprecated Circuit methods that must still work."""

    def test_front_input_warns_and_works(self):
        circuit = Circuit("AA-BB-CC-DD-EE-FF")

        with pytest.warns(DeprecationWarning):
            result = circuit.front_input(0)

        assert isinstance(result, Input), (
            f"front_input() should return an Input instance, got {type(result)}"
        )
        assert result.port == 0, (
            f"front_input(0) should allocate port 0, got port {result.port}"
        )

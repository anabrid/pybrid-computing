# Copyright (c) 2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
Unit tests for Circuit lane allocation and routing logic.

Tests the internal lane allocation mechanisms:
- General-purpose lane pool (0-31, lanes 24-31 shared with ACL I/O)
- Constant lane constraints (clane 14 -> lanes 16-31, clane 15 -> lanes 0-15)
- Weight splitting allocation
- Lane exhaustion handling
"""

import pytest
from pybrid.lucipy.circuits import Circuit


class TestGeneralLaneAllocation:
    """Tests for general-purpose lane allocation (lanes 0-23)."""

    def test_lanes_allocated_sequentially(self):
        circuit = Circuit("AA-BB-CC-DD-EE-FF")
        integrators = [circuit.int() for _ in range(8)]

        for i in range(5):
            src_idx = i % 8
            tgt_idx = (i + 1) % 8
            circuit.connect(integrators[src_idx], integrators[tgt_idx], weight=1.0)

        assert circuit._general_lanes_used[0:5] == [True] * 5
        assert circuit._general_lanes_used[5:] == [False] * 27


class TestConstantMBlockOutput:
    """Tests for constant M-block output selection based on allocated lane.

    The constant giver is a single physical unit accessible via M-block
    output 15 (lanes 0-15) and output 14 (lanes 16-31).  Lane allocation
    is unconstrained; the correct output is determined after allocation.
    """

    def test_constant_after_partial_fill_skips_used_lanes(self):
        circuit = Circuit("AA-BB-CC-DD-EE-FF")
        integrators = [circuit.int() for _ in range(8)]

        for i in range(11):
            circuit.connect(integrators[i % 8], integrators[(i + 1) % 8], weight=1.0)

        c0 = circuit.const(value=1.0)
        circuit.connect(c0, integrators[0], weight=1.0)

        cluster = circuit.to_computer().entities[0].clusters[0]

        assert cluster.ublock.outputs[11] == 15, (
            f"Constant on lane 11 should use M-block output 15, "
            f"got {cluster.ublock.outputs[11]}"
        )


class TestWeightSplitting:
    """Tests for weight splitting across multiple lanes."""

    @pytest.mark.parametrize("weight,expected_lanes", [
        (24.0, 3),
        (-20.0, 3),
    ])
    def test_weight_splitting(self, weight, expected_lanes):
        """Weight splitting allocates ceil(|weight|/8) lanes, including negative weights."""
        circuit = Circuit("AA-BB-CC-DD-EE-FF")
        i0 = circuit.int()
        i1 = circuit.int()

        circuit.connect(i0, i1, weight=weight)

        used_count = sum(circuit._general_lanes_used)
        assert used_count == expected_lanes, (
            f"weight={weight} should use {expected_lanes} lanes, got {used_count}"
        )


class TestLaneExhaustion:
    """Tests for lane exhaustion and validation."""

    def test_constant_lane_exhaustion(self):
        circuit = Circuit("AA-BB-CC-DD-EE-FF")
        integrators = [circuit.int() for _ in range(8)]

        for i in range(32):
            src_idx = i % 8
            tgt_idx = (i + 1) % 8
            circuit.connect(integrators[src_idx], integrators[tgt_idx], weight=1.0)

        c0 = circuit.const(value=1.0)

        with pytest.raises(ValueError, match="(?i)lane|free"):
            circuit.connect(c0, integrators[0], weight=1.0)

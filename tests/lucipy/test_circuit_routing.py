# Copyright (c) 2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
Unit tests for Circuit lane allocation and routing logic.

Tests the internal lane allocation mechanisms:
- General-purpose lane pool (0-31, lanes 24-31 shared with ACL I/O)
- Constant lane constraints (clane 14 -> lanes 16-31, clane 15 -> lanes 0-15)
- Weight splitting allocation
- Validate-then-commit semantics
- Lane exhaustion handling
"""

import pytest
from pybrid.lucipy.circuits import Circuit


class TestGeneralLaneAllocation:
    """Tests for general-purpose lane allocation (lanes 0-23)."""

    def test_lanes_allocated_sequentially(self):
        """Lanes are allocated sequentially from the general pool."""
        circuit = Circuit()
        integrators = [circuit.int() for _ in range(8)]

        # Make 5 connections, should use lanes 0-4
        for i in range(5):
            src_idx = i % 8
            tgt_idx = (i + 1) % 8
            circuit.connect(integrators[src_idx], integrators[tgt_idx], weight=1.0)

        # Check internal state: first 5 lanes should be used
        assert circuit._general_lanes_used[0:5] == [True] * 5
        assert circuit._general_lanes_used[5:] == [False] * 27

    def test_lane_tracking_accurate_after_multiple_connections(self):
        """Lane tracking remains accurate across multiple connections."""
        circuit = Circuit()
        i0 = circuit.int()
        i1 = circuit.int()
        i2 = circuit.int()

        circuit.connect(i0, i1, weight=1.0)  # uses 1 lane
        circuit.connect(i1, i2, weight=1.0)  # uses 1 lane
        circuit.connect(i2, i0, weight=1.0)  # uses 1 lane

        used_count = sum(circuit._general_lanes_used)
        assert used_count == 3, f"Expected 3 lanes used, got {used_count}"


class TestConstantMBlockOutput:
    """Tests for constant M-block output selection based on allocated lane.

    The constant giver is a single physical unit accessible via M-block
    output 15 (lanes 0-15) and output 14 (lanes 16-31).  Lane allocation
    is unconstrained; the correct output is determined after allocation.
    """

    def test_constant_on_fresh_pool_uses_lane_0(self):
        """On a fresh pool, constant connection uses lane 0 (first free)."""
        circuit = Circuit()
        c0 = circuit.const(value=1.0)
        i0 = circuit.int()

        circuit.connect(c0, i0, weight=1.0)

        cluster = circuit.to_computer().entities[0].clusters[0]

        # Lane 0 is in range 0-15 -> M-block output 15
        assert cluster.ublock.outputs[0] == 15, (
            f"Constant on lane 0 should use M-block output 15, "
            f"got {cluster.ublock.outputs[0]}"
        )

    def test_constant_after_partial_fill_skips_used_lanes(self):
        """Constant uses first free lane even when some lanes are occupied."""
        circuit = Circuit()
        integrators = [circuit.int() for _ in range(8)]

        # Fill lanes 0-10 with regular connections
        for i in range(11):
            circuit.connect(integrators[i % 8], integrators[(i + 1) % 8], weight=1.0)

        c0 = circuit.const(value=1.0)
        circuit.connect(c0, integrators[0], weight=1.0)

        cluster = circuit.to_computer().entities[0].clusters[0]

        # Lane 11 is first free, in range 0-15 -> output 15
        assert cluster.ublock.outputs[11] == 15, (
            f"Constant on lane 11 should use M-block output 15, "
            f"got {cluster.ublock.outputs[11]}"
        )

    def test_constant_on_lane_16_uses_output_14(self):
        """Constant routed to lanes 16+ uses M-block output 14."""
        circuit = Circuit()
        integrators = [circuit.int() for _ in range(8)]

        # Fill lanes 0-15
        for i in range(16):
            circuit.connect(integrators[i % 8], integrators[(i + 1) % 8], weight=1.0)

        c0 = circuit.const(value=1.0)
        circuit.connect(c0, integrators[0], weight=1.0)

        cluster = circuit.to_computer().entities[0].clusters[0]

        # Lane 16 is first free, in range 16-31 -> output 14
        assert cluster.ublock.outputs[16] == 14, (
            f"Constant on lane 16 should use M-block output 14, "
            f"got {cluster.ublock.outputs[16]}"
        )


class TestWeightSplitting:
    """Tests for weight splitting across multiple lanes."""

    def test_weight_splitting_allocates_correct_number_of_lanes(self):
        """Weight splitting allocates ceil(|weight|/8) lanes."""
        circuit = Circuit()
        i0 = circuit.int()
        i1 = circuit.int()

        # weight=16.0 should split into ceil(16/8)=2 lanes
        circuit.connect(i0, i1, weight=16.0)

        used_count = sum(circuit._general_lanes_used)
        assert used_count == 2, f"weight=16.0 should use 2 lanes, got {used_count}"

    def test_weight_splitting_with_24_lanes(self):
        """Weight=24.0 splits into ceil(24/8)=3 lanes."""
        circuit = Circuit()
        i0 = circuit.int()
        i1 = circuit.int()

        circuit.connect(i0, i1, weight=24.0)

        used_count = sum(circuit._general_lanes_used)
        assert used_count == 3, f"weight=24.0 should use 3 lanes, got {used_count}"

    def test_weight_splitting_negative_weights(self):
        """Negative weights also split correctly (uses absolute value)."""
        circuit = Circuit()
        i0 = circuit.int()
        i1 = circuit.int()

        # weight=-20.0 should split into ceil(20/8)=3 lanes
        circuit.connect(i0, i1, weight=-20.0)

        used_count = sum(circuit._general_lanes_used)
        assert used_count == 3, f"weight=-20.0 should use 3 lanes, got {used_count}"


class TestLaneExhaustion:
    """Tests for lane exhaustion and validation."""

    def test_cannot_allocate_beyond_32_lanes(self):
        """Cannot allocate more than 32 lanes (0-31)."""
        circuit = Circuit()
        integrators = [circuit.int() for _ in range(8)]

        # Fill all 32 lanes
        for i in range(32):
            circuit.connect(integrators[i % 8], integrators[(i + 1) % 8], weight=1.0)

        # 33rd connection should fail
        with pytest.raises(ValueError, match="(?i)lane|free|connection"):
            circuit.connect(integrators[0], integrators[1], weight=1.0)

    def test_lane_exhaustion_with_weight_splitting(self):
        """Lane exhaustion is detected correctly with weight splitting."""
        circuit = Circuit()
        integrators = [circuit.int() for _ in range(8)]

        # Fill 31 lanes (out of 32 total)
        for i in range(31):
            circuit.connect(integrators[i % 8], integrators[(i + 1) % 8], weight=1.0)

        # Try to connect with weight=10.0 (needs 2 lanes, only 1 free)
        with pytest.raises(ValueError, match="(?i)lane|free"):
            circuit.connect(integrators[0], integrators[1], weight=10.0)

    def test_constant_lane_exhaustion(self):
        """Constant connections fail when all lanes are full."""
        circuit = Circuit()
        integrators = [circuit.int() for _ in range(8)]

        # Fill all 32 lanes (0-31) with regular connections.
        # This ensures lanes 16-31 (where clane 14 constants must go) are
        # fully occupied.
        for i in range(32):
            src_idx = i % 8
            tgt_idx = (i + 1) % 8
            circuit.connect(integrators[src_idx], integrators[tgt_idx], weight=1.0)

        # Now try to connect a constant — all 32 lanes are full, so it must fail
        c0 = circuit.const(value=1.0)

        with pytest.raises(ValueError, match="(?i)lane|free"):
            circuit.connect(c0, integrators[0], weight=1.0)


class TestValidateThenCommit:
    """Tests for validate-then-commit semantics."""

    def test_failed_connection_does_not_mutate_lane_state(self):
        """Failed connections leave lane allocation unchanged."""
        circuit = Circuit()
        integrators = [circuit.int() for _ in range(8)]

        # Fill 30 lanes (out of 32 total)
        for i in range(30):
            circuit.connect(integrators[i % 8], integrators[(i + 1) % 8], weight=1.0)

        # Capture lane state before failed connection
        lanes_before = circuit._general_lanes_used[:]

        # Try to connect with weight=20.0 (needs 3 lanes, only 2 free) - should fail
        try:
            circuit.connect(integrators[0], integrators[1], weight=20.0)
        except ValueError:
            pass  # expected

        # Lane state should be unchanged
        lanes_after = circuit._general_lanes_used
        assert lanes_before == lanes_after, (
            "Lane state was mutated despite failed connection (validate-then-commit violated)"
        )

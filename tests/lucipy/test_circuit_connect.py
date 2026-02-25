# Copyright (c) 2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
Unit tests for Circuit.connect() connection logic.

These tests verify that connect(source, target, weight) correctly:
- Allocates lanes from the general-purpose pool (0-23)
- Sets UBlock output, CBlock coefficient, and IBlock output on the pybrid object
- Performs weight splitting for large weights (ceil(|weight|/8) lanes)
- Implements validate-then-commit (no state mutation on failure)
- Handles special cases: constants (lane halves), inputs (skip UBlock),
  outputs (skip IBlock)

Uses DummyDAC-independent unit tests; no hardware required.
"""

import math
import copy
import warnings
import pytest

from pybrid.lucipy.circuits import (
    Circuit,
    Integrator,
    Multiplier,
    _MulInput,
    Identity,
    Constant,
    Input,
    Output,
)
from pybrid.lucidac.computer import LUCIDAC


class TestConnectBasic:
    """Tests for basic connect() operations between computing elements."""

    def test_connect_integrator_to_integrator(self):
        """Connecting i0->i1 with weight=1.0 sets U-block output, C-block coefficient, and I-block route."""
        circuit = Circuit("AA-BB-CC-DD-EE-FF")
        i0 = circuit.int()
        i1 = circuit.int()

        circuit.connect(i0, i1, weight=1.0)

        lucidac = circuit.to_computer()
        cluster = lucidac.entities[0].clusters[0]

        # Find the lane that was allocated for this connection.
        # UBlock: outputs[lane] should be the source output (i0.lane = i0.id = 0)
        allocated_lanes = [
            lane for lane in range(24)
            if cluster.ublock.outputs[lane] == i0.lane
        ]
        assert len(allocated_lanes) >= 1, (
            f"Expected at least 1 lane with UBlock output pointing to integrator {i0.id} "
            f"(lane {i0.lane}), found none"
        )

        lane = allocated_lanes[0]

        # CBlock: coefficient at this lane should be 1.0
        c_factor = cluster.cblock.elements[lane].computation.factor
        assert c_factor == pytest.approx(1.0), (
            f"CBlock coefficient at lane {lane} should be 1.0, got {c_factor}"
        )

        # IBlock: outputs[i1.lane] should contain the allocated lane
        i_output = cluster.iblock.outputs[i1.lane]
        assert lane in i_output, (
            f"IBlock outputs[{i1.lane}] should contain lane {lane}, "
            f"got {i_output}"
        )

    def test_connect_with_negative_weight(self):
        circuit = Circuit("AA-BB-CC-DD-EE-FF")
        i0 = circuit.int()
        i1 = circuit.int()

        circuit.connect(i0, i1, weight=-1.0)

        lucidac = circuit.to_computer()
        cluster = lucidac.entities[0].clusters[0]

        # Find the allocated lane
        allocated_lanes = [
            lane for lane in range(24)
            if cluster.ublock.outputs[lane] == i0.lane
        ]
        assert len(allocated_lanes) >= 1, (
            "Expected at least 1 lane allocated for the connection"
        )

        lane = allocated_lanes[0]
        c_factor = cluster.cblock.elements[lane].computation.factor
        assert c_factor == pytest.approx(-1.0), (
            f"CBlock coefficient should be -1.0 for negative weight, got {c_factor}"
        )

    def test_connect_multiplier_output_to_integrator(self):
        circuit = Circuit("AA-BB-CC-DD-EE-FF")
        m0 = circuit.mul()
        i0 = circuit.int()

        circuit.connect(m0, i0, weight=1.0)

        lucidac = circuit.to_computer()
        cluster = lucidac.entities[0].clusters[0]

        # UBlock should have a lane pointing to m0.lane (8 + m0.id)
        allocated_lanes = [
            lane for lane in range(24)
            if cluster.ublock.outputs[lane] == m0.lane
        ]
        assert len(allocated_lanes) >= 1, (
            f"Expected at least 1 lane with UBlock output pointing to multiplier "
            f"lane {m0.lane}, found none"
        )

        lane = allocated_lanes[0]

        # IBlock should route to i0.lane
        assert lane in cluster.iblock.outputs[i0.lane], (
            f"IBlock outputs[{i0.lane}] should contain lane {lane}"
        )


class TestConnectConstant:
    """Tests for connecting constant sources.

    The constant giver is a single physical unit.  Its output appears on
    M-block output 15 (routable to lanes 0-15) and output 14 (routable to
    lanes 16-31).  Lane allocation is unconstrained — the first free lane
    is used, and the M-block output is determined by the allocated lane's
    range.
    """

    def test_connect_constant_uses_first_free_lane(self):
        circuit = Circuit("AA-BB-CC-DD-EE-FF")
        c0 = circuit.const(value=1.0)
        i0 = circuit.int()

        circuit.connect(c0, i0, weight=1.0)

        # Lane 0 should be the first free lane (greedy, starting from 0)
        assert circuit._general_lanes_used[0], (
            "Lane 0 should be used for the constant connection"
        )

    def test_constant_on_lane_0_15_uses_mblock_output_15(self):
        circuit = Circuit("AA-BB-CC-DD-EE-FF")
        c0 = circuit.const(value=1.0)
        i0 = circuit.int()

        circuit.connect(c0, i0, weight=1.0)

        cluster = circuit.to_computer().entities[0].clusters[0]

        # First free lane is 0 (in range 0-15), so UBlock output should be 15
        assert cluster.ublock.outputs[0] == 15, (
            f"Constant on lane 0 (range 0-15) should use M-block output 15, "
            f"got {cluster.ublock.outputs[0]}"
        )

    def test_constant_on_lane_16_31_uses_mblock_output_14(self):
        circuit = Circuit("AA-BB-CC-DD-EE-FF")
        integrators = [circuit.int() for _ in range(8)]

        # Fill lanes 0-15 with standard connections
        for i in range(16):
            circuit.connect(integrators[i % 8], integrators[(i + 1) % 8], weight=1.0)

        c0 = circuit.const(value=1.0)
        circuit.connect(c0, integrators[0], weight=1.0)

        cluster = circuit.to_computer().entities[0].clusters[0]

        # First free lane is 16 (in range 16-31), so UBlock output should be 14
        assert cluster.ublock.outputs[16] == 14, (
            f"Constant on lane 16 (range 16-31) should use M-block output 14, "
            f"got {cluster.ublock.outputs[16]}"
        )

    def test_constant_iblock_routes_to_target(self):
        circuit = Circuit("AA-BB-CC-DD-EE-FF")
        c0 = circuit.const(value=1.0)
        i0 = circuit.int()

        circuit.connect(c0, i0, weight=1.0)

        cluster = circuit.to_computer().entities[0].clusters[0]

        # Lane 0 should route to i0 via IBlock
        assert 0 in cluster.iblock.outputs[i0.lane], (
            f"IBlock outputs[{i0.lane}] should contain lane 0"
        )

    def test_constant_weight_split_across_ranges(self):
        """When weight splitting spans both lane ranges, each lane uses the correct M-block output (14 or 15)."""
        circuit = Circuit("AA-BB-CC-DD-EE-FF")
        integrators = [circuit.int() for _ in range(8)]

        # Fill lanes 0-13 so only lanes 14, 15, 16, 17, ... are free
        for i in range(14):
            circuit.connect(integrators[i % 8], integrators[(i + 1) % 8], weight=1.0)

        # weight=10.0 -> ceil(10/8)=2 lanes needed
        # Should use lanes 14 (range 0-15 -> output 15) and 15 (range 0-15 -> output 15)
        # or lanes 14, 15 both in 0-15 -> output 15. Let's force a cross-range split:
        # Fill lane 14 too, so free lanes start at 15, 16, ...
        circuit.connect(integrators[0], integrators[1], weight=1.0)  # lane 14

        c0 = circuit.const(value=1.0)
        circuit.connect(c0, integrators[2], weight=10.0)

        cluster = circuit.to_computer().entities[0].clusters[0]

        # Lane 15 is in range 0-15 -> output 15
        assert cluster.ublock.outputs[15] == 15, (
            f"Constant on lane 15 should use M-block output 15, "
            f"got {cluster.ublock.outputs[15]}"
        )
        # Lane 16 is in range 16-31 -> output 14
        assert cluster.ublock.outputs[16] == 14, (
            f"Constant on lane 16 should use M-block output 14, "
            f"got {cluster.ublock.outputs[16]}"
        )


class TestConnectWeightSplitting:
    """Tests for weight splitting across multiple lanes."""

    def test_connect_large_weight_splits_lanes(self):
        """weight=20.0 allocates ceil(20/8)=3 lanes with effective coefficient 20.0/3 each."""
        circuit = Circuit("AA-BB-CC-DD-EE-FF")
        i0 = circuit.int()
        i1 = circuit.int()

        circuit.connect(i0, i1, weight=20.0)

        lucidac = circuit.to_computer()
        cluster = lucidac.entities[0].clusters[0]

        expected_n_lanes = math.ceil(abs(20.0) / 8)
        assert expected_n_lanes == 3, "Sanity: ceil(20/8) == 3"

        # Find all lanes allocated for this connection (i0 -> i1)
        allocated_lanes = [
            lane for lane in range(24)
            if cluster.ublock.outputs[lane] == i0.lane
        ]
        assert len(allocated_lanes) == expected_n_lanes, (
            f"Expected {expected_n_lanes} lanes for weight=20.0, "
            f"got {len(allocated_lanes)}"
        )

        expected_coeff = 20.0 / expected_n_lanes
        for lane in allocated_lanes:
            # The actual C-block value may be stored as scaled (factor/8 if >1)
            # but the semantic coefficient should be weight/n_lanes
            c_factor = cluster.cblock.elements[lane].computation.factor
            # After upscaling, the effective factor is c_factor * 8 if upscaling is set,
            # or c_factor if not. The implementation should store the correctly scaled value.
            upscaled = cluster.iblock.upscaling[lane]
            effective = c_factor * 8 if upscaled else c_factor
            assert effective == pytest.approx(expected_coeff, abs=1e-9), (
                f"Effective coefficient at lane {lane} should be {expected_coeff}, "
                f"got {effective} (raw factor={c_factor}, upscaled={upscaled})"
            )

        # All lanes should route to i1 via IBlock
        for lane in allocated_lanes:
            assert lane in cluster.iblock.outputs[i1.lane], (
                f"IBlock outputs[{i1.lane}] should contain lane {lane}"
            )


class TestConnectACL:
    """Tests for connecting Input/Output (ACL) elements."""

    def test_connect_input_to_integrator(self):
        """ACL_IN path: U-block is bypassed (output=None/-1), I-block routes ACL lane to integrator."""
        circuit = Circuit("AA-BB-CC-DD-EE-FF")
        inp = circuit.input()
        i0 = circuit.int()

        circuit.connect(inp, i0, weight=1.0)

        lucidac = circuit.to_computer()
        cluster = lucidac.entities[0].clusters[0]

        # For ACL_IN, the lane should be the input's lane (24-31)
        acl_lane = inp.lane

        # UBlock output at this lane should be None/-1 (no U-block connection
        # for ACL_IN path)
        u_output = cluster.ublock.outputs[acl_lane]
        assert u_output is None or u_output == -1, (
            f"UBlock output at ACL lane {acl_lane} should be None/-1 for "
            f"ACL_IN path, got {u_output}"
        )

        # IBlock should route the ACL lane to the integrator input
        assert acl_lane in cluster.iblock.outputs[i0.lane], (
            f"IBlock outputs[{i0.lane}] should contain ACL lane {acl_lane}"
        )

    def test_connect_input_ignores_weight(self):
        """ACL_IN bypasses U-block and C-block; weight is silently ignored and C-block stays at default 1.0."""
        circuit = Circuit("AA-BB-CC-DD-EE-FF")
        inp = circuit.input()
        i0 = circuit.int()

        # weight=5.0 would require upscaling on a standard path, but ACL_IN
        # has no C-block so it must be ignored without error.
        circuit.connect(inp, i0, weight=5.0)

        lucidac = circuit.to_computer()
        cluster = lucidac.entities[0].clusters[0]

        acl_lane = inp.lane

        # U-block must NOT be set for this ACL lane
        u_output = cluster.ublock.outputs[acl_lane]
        assert u_output is None or u_output == -1, (
            f"UBlock output at ACL lane {acl_lane} should be None/-1 for "
            f"ACL_IN path, got {u_output}"
        )

        # C-block coefficient must remain at the default (1.0) — not set to 5.0
        c_factor = cluster.cblock.elements[acl_lane].computation.factor
        assert c_factor == pytest.approx(1.0), (
            f"CBlock factor at ACL lane {acl_lane} should be untouched "
            f"(default 1.0), got {c_factor}"
        )

        # I-block routing must still happen
        assert acl_lane in cluster.iblock.outputs[i0.lane], (
            f"IBlock outputs[{i0.lane}] should contain ACL lane {acl_lane}"
        )

    def test_connect_integrator_to_output(self):
        """ACL_OUT path: U-block routes integrator to ACL lane; I-block is not used for that lane."""
        circuit = Circuit("AA-BB-CC-DD-EE-FF")
        i0 = circuit.int()
        out = circuit.output()

        circuit.connect(i0, out, weight=1.0)

        lucidac = circuit.to_computer()
        cluster = lucidac.entities[0].clusters[0]

        # For ACL_OUT, the lane should be the output's lane (24-31)
        acl_lane = out.lane

        # UBlock should connect integrator output to this lane
        u_output = cluster.ublock.outputs[acl_lane]
        assert u_output == i0.lane, (
            f"UBlock output at ACL lane {acl_lane} should be {i0.lane} "
            f"(integrator output), got {u_output}"
        )

        # IBlock should NOT route this lane to any M-block input
        # (ACL_OUT goes directly to front panel, bypassing I-block)
        for m_input in range(16):
            assert acl_lane not in cluster.iblock.outputs[m_input], (
                f"ACL_OUT lane {acl_lane} should not appear in any IBlock output, "
                f"but found in outputs[{m_input}]"
            )

    def test_connect_output_with_valid_weight(self):
        """ACL_OUT with fractional weight sets C-block coefficient correctly."""
        circuit = Circuit("AA-BB-CC-DD-EE-FF")
        i0 = circuit.int()
        out = circuit.output()

        circuit.connect(i0, out, weight=0.5)

        lucidac = circuit.to_computer()
        cluster = lucidac.entities[0].clusters[0]
        acl_lane = out.lane

        # U-block routes source to ACL lane
        assert cluster.ublock.outputs[acl_lane] == i0.lane, (
            f"UBlock output at ACL lane {acl_lane} should be {i0.lane}"
        )

        # C-block coefficient set to 0.5
        c_factor = cluster.cblock.elements[acl_lane].computation.factor
        assert c_factor == pytest.approx(0.5), (
            f"CBlock coefficient at ACL lane {acl_lane} should be 0.5, "
            f"got {c_factor}"
        )

    def test_connect_output_with_negative_weight(self):
        circuit = Circuit("AA-BB-CC-DD-EE-FF")
        i0 = circuit.int()
        out = circuit.output()

        circuit.connect(i0, out, weight=-0.75)

        lucidac = circuit.to_computer()
        cluster = lucidac.entities[0].clusters[0]
        acl_lane = out.lane

        c_factor = cluster.cblock.elements[acl_lane].computation.factor
        assert c_factor == pytest.approx(-0.75), (
            f"CBlock coefficient should be -0.75, got {c_factor}"
        )

    @pytest.mark.parametrize("weight", [2.0, -3.0])
    def test_connect_output_rejects_weight_outside_range(self, weight):
        circuit = Circuit("AA-BB-CC-DD-EE-FF")
        i0 = circuit.int()
        out = circuit.output()

        with pytest.raises(ValueError, match="(?i)weight|acl|output|range"):
            circuit.connect(i0, out, weight=weight)


class TestConnectIdentity:
    """Tests for Identity elements in connect()."""

    def test_identity_as_source_in_connect(self):
        """Identity as source routes via M-block output 12+offset through U-block and I-block."""
        circuit = Circuit("AA-BB-CC-DD-EE-FF")
        m0 = circuit.mul()
        id0 = m0.b.id()  # offset=1, M-block output 13
        i0 = circuit.int()

        circuit.connect(id0, i0, weight=1.0)

        lucidac = circuit.to_computer()
        cluster = lucidac.entities[0].clusters[0]

        expected_source_lane = 12 + id0.offset  # = 13

        # Find lane(s) where U-block output points to the identity source lane
        allocated_lanes = [
            lane for lane in range(24)
            if cluster.ublock.outputs[lane] == expected_source_lane
        ]
        assert len(allocated_lanes) >= 1, (
            f"Expected at least 1 lane with UBlock output pointing to identity "
            f"output lane {expected_source_lane}, found none"
        )

        lane = allocated_lanes[0]

        # I-block should route to integrator input
        assert lane in cluster.iblock.outputs[i0.lane], (
            f"IBlock outputs[{i0.lane}] should contain lane {lane}"
        )

    def test_identity_as_target_raises(self):
        circuit = Circuit("AA-BB-CC-DD-EE-FF")
        inp = circuit.input()
        m0 = circuit.mul()
        id0 = m0.a.id()

        with pytest.raises(TypeError):
            circuit.connect(inp, id0, weight=1.0)


class TestConnectRoutingErrors:
    """Tests for invalid routing directions."""

    def test_connect_from_output_raises_type_error(self):
        circuit = Circuit("AA-BB-CC-DD-EE-FF")
        out = circuit.output()
        i0 = circuit.int()

        with pytest.raises(TypeError):
            circuit.connect(out, i0, weight=1.0)

    def test_connect_to_input_raises_type_error(self):
        circuit = Circuit("AA-BB-CC-DD-EE-FF")
        i0 = circuit.int()
        inp = circuit.input()

        with pytest.raises(TypeError):
            circuit.connect(i0, inp, weight=1.0)


class TestConnectValidation:
    """Tests for validate-then-commit behavior and lane exhaustion."""

    def test_connect_validates_before_commit(self):
        """A connect() that needs more lanes than available must raise ValueError without mutating state."""
        circuit = Circuit("AA-BB-CC-DD-EE-FF")
        integrators = [circuit.int() for _ in range(8)]

        # Fill 31 of 32 total lanes (0-31) with weight=1.0 connections
        for lane_idx in range(31):
            src_idx = lane_idx % 8
            tgt_idx = (lane_idx + 1) % 8
            circuit.connect(integrators[src_idx], integrators[tgt_idx], weight=1.0)

        # Capture state before the failing connect
        lucidac_before = circuit.to_computer()
        state_snapshot = copy.deepcopy(lucidac_before)

        # Now try to connect needing 2 lanes (weight=10.0 -> ceil(10/8)=2)
        # Only 1 lane is free, so this must fail
        with pytest.raises(ValueError):
            circuit.connect(integrators[0], integrators[1], weight=10.0)

        # Verify no state mutation occurred
        lucidac_after = circuit.to_computer()
        cluster_after = lucidac_after.entities[0].clusters[0]
        cluster_before = state_snapshot.entities[0].clusters[0]

        # UBlock outputs should be unchanged
        assert cluster_after.ublock.outputs == cluster_before.ublock.outputs, (
            "UBlock outputs must not change after a failed connect()"
        )

    def test_connect_exhausts_lanes(self):
        circuit = Circuit("AA-BB-CC-DD-EE-FF")
        integrators = [circuit.int() for _ in range(8)]

        # Fill all 32 lanes
        for lane_idx in range(32):
            src_idx = lane_idx % 8
            tgt_idx = (lane_idx + 1) % 8
            circuit.connect(integrators[src_idx], integrators[tgt_idx], weight=1.0)

        # The next connection should fail
        with pytest.raises(ValueError, match="(?i)lane|occupied|free|connection"):
            circuit.connect(integrators[0], integrators[1], weight=1.0)


class TestConnectExtendedLanePool:
    """Tests for extended lane allocation using lanes 24-31 for general signals."""

    def test_general_signal_spills_to_lane_24_plus(self):
        circuit = Circuit("AA-BB-CC-DD-EE-FF")
        integrators = [circuit.int() for _ in range(8)]

        # Fill lanes 0-23
        for lane_idx in range(24):
            src_idx = lane_idx % 8
            tgt_idx = (lane_idx + 1) % 8
            circuit.connect(integrators[src_idx], integrators[tgt_idx], weight=1.0)

        # 25th connection should succeed using lane 24+
        circuit.connect(integrators[0], integrators[1], weight=1.0)

        cluster = circuit.to_computer().entities[0].clusters[0]
        allocated_special = [
            lane for lane in range(24, 32)
            if cluster.ublock.outputs[lane] == integrators[0].lane
        ]
        assert len(allocated_special) >= 1, (
            "Expected at least 1 lane in 24-31 to be used for spill-over"
        )

    def test_general_signal_skips_acl_occupied_lane(self):
        """General signal spill skips ACL-occupied lanes and uses the next free one."""
        circuit = Circuit("AA-BB-CC-DD-EE-FF")
        integrators = [circuit.int() for _ in range(8)]
        circuit.input(port=0)  # blocks lane 24

        # Fill lanes 0-23
        for lane_idx in range(24):
            src_idx = lane_idx % 8
            tgt_idx = (lane_idx + 1) % 8
            circuit.connect(integrators[src_idx], integrators[tgt_idx], weight=1.0)

        # Next general signal should skip lane 24, land on lane 25
        circuit.connect(integrators[0], integrators[2], weight=1.0)

        cluster = circuit.to_computer().entities[0].clusters[0]
        assert cluster.ublock.outputs[25] == integrators[0].lane, (
            f"Expected lane 25 to be used (skipping ACL port 0 on lane 24), "
            f"got UBlock output at lane 25 = {cluster.ublock.outputs[25]}"
        )

    @pytest.mark.parametrize("acl_method", ["input", "output"])
    def test_acl_fails_if_lane_occupied_by_general_signal(self, acl_method):
        circuit = Circuit("AA-BB-CC-DD-EE-FF")
        integrators = [circuit.int() for _ in range(8)]

        # Fill lanes 0-24 (lane 24 occupied by general signal spill-over)
        for lane_idx in range(25):
            src_idx = lane_idx % 8
            tgt_idx = (lane_idx + 1) % 8
            circuit.connect(integrators[src_idx], integrators[tgt_idx], weight=1.0)

        with pytest.raises(ValueError, match="(?i)(try|other|different).*(lane|port)"):
            getattr(circuit, acl_method)(port=0)

    def test_acl_port_succeeds_if_lane_not_used(self):
        circuit = Circuit("AA-BB-CC-DD-EE-FF")
        integrators = [circuit.int() for _ in range(8)]

        # Use only some lanes 0-23
        for lane_idx in range(10):
            src_idx = lane_idx % 8
            tgt_idx = (lane_idx + 1) % 8
            circuit.connect(integrators[src_idx], integrators[tgt_idx], weight=1.0)

        # input(port=0) should succeed — lane 24 is free
        inp = circuit.input(port=0)
        assert inp.lane == 24

    def test_constant_spills_to_lanes_24_31(self):
        """Constant connection in spill range 24-31 uses M-block output 14 (range 16-31)."""
        circuit = Circuit("AA-BB-CC-DD-EE-FF")
        integrators = [circuit.int() for _ in range(8)]

        # Fill lanes 0-23 with general connections
        for lane_idx in range(24):
            src_idx = lane_idx % 8
            tgt_idx = (lane_idx + 1) % 8
            circuit.connect(integrators[src_idx], integrators[tgt_idx], weight=1.0)

        c0 = circuit.const(value=1.0)
        circuit.connect(c0, integrators[0], weight=1.0)

        cluster = circuit.to_computer().entities[0].clusters[0]
        # Lane 24 is first free, in range 16-31 -> output 14
        assert cluster.ublock.outputs[24] == 14, (
            f"Constant on lane 24 should use M-block output 14, "
            f"got {cluster.ublock.outputs[24]}"
        )

    def test_total_capacity_32_minus_acl_ports(self):
        """With 2 ACL ports allocated, only 30 general connections fit; the 31st must raise ValueError."""
        circuit = Circuit("AA-BB-CC-DD-EE-FF")
        integrators = [circuit.int() for _ in range(8)]
        circuit.input(port=0)   # blocks lane 24
        circuit.output(port=1)  # blocks lane 25

        # 30 connections should succeed (lanes 0-23 + 26-31 = 30 free lanes)
        for lane_idx in range(30):
            src_idx = lane_idx % 8
            tgt_idx = (lane_idx + 1) % 8
            circuit.connect(integrators[src_idx], integrators[tgt_idx], weight=1.0)

        # 31st should fail
        with pytest.raises(ValueError, match="(?i)lane|occupied|free|connection"):
            circuit.connect(integrators[0], integrators[1], weight=1.0)

    def test_validate_then_commit_extended_pool(self):
        """Validate-before-commit: a 2-lane connect into 1 free slot must fail without mutating state."""
        circuit = Circuit("AA-BB-CC-DD-EE-FF")
        integrators = [circuit.int() for _ in range(8)]

        # Fill 31 lanes
        for lane_idx in range(31):
            src_idx = lane_idx % 8
            tgt_idx = (lane_idx + 1) % 8
            circuit.connect(integrators[src_idx], integrators[tgt_idx], weight=1.0)

        state_snapshot = copy.deepcopy(circuit.to_computer())

        with pytest.raises(ValueError):
            circuit.connect(integrators[0], integrators[1], weight=10.0)

        # Verify no state mutation
        cluster_after = circuit.to_computer().entities[0].clusters[0]
        cluster_before = state_snapshot.entities[0].clusters[0]
        assert cluster_after.ublock.outputs == cluster_before.ublock.outputs, (
            "UBlock outputs must not change after a failed connect()"
        )


class TestConstantIdentityShadowing:
    """Tests for warnings when constant giver shadows Identity outputs 14/15.

    The constant giver uses M-block outputs 14 and 15 — the same physical
    outputs as Identity(offset=2) and Identity(offset=3).  When the constant
    giver is active (any constant allocated), it shadows these identity
    passthroughs, making them useless.
    """

    @pytest.mark.parametrize("id_input,offset", [("a", 2), ("b", 3)])
    def test_connect_identity_high_offset_after_const_warns(self, id_input, offset):
        """Connecting Identity(offset=2 or 3) when constant giver is active warns."""
        circuit = Circuit("AA-BB-CC-DD-EE-FF")
        circuit.const(value=1.0)  # turns on constant giver
        circuit.mul()  # mul0
        m1 = circuit.mul()  # mul1
        identity = getattr(m1, id_input).id()
        i0 = circuit.int()

        with pytest.warns(UserWarning, match="(?i)shadow|constant.*giver|identity"):
            circuit.connect(identity, i0, weight=1.0)

    @pytest.mark.parametrize("id_input,offset", [("a", 0), ("b", 1)])
    def test_connect_identity_low_offset_after_const_no_warning(self, id_input, offset):
        """Identity(offset=0 or 1) is not affected by constant giver — no warning."""
        circuit = Circuit("AA-BB-CC-DD-EE-FF")
        circuit.const(value=1.0)
        m0 = circuit.mul()
        identity = getattr(m0, id_input).id()
        i0 = circuit.int()

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            circuit.connect(identity, i0, weight=1.0)
            shadowing_warnings = [
                x for x in w
                if issubclass(x.category, UserWarning)
                and "shadow" in str(x.message).lower()
            ]
            assert len(shadowing_warnings) == 0, (
                f"Identity(offset={offset}) should not trigger shadowing warning, "
                f"got: {[str(x.message) for x in shadowing_warnings]}"
            )

    @pytest.mark.parametrize("id_input,offset", [("a", 2), ("b", 3)])
    def test_const_after_identity_high_offset_connected_warns(self, id_input, offset):
        """Allocating a constant after Identity(offset=2 or 3) was connected warns."""
        circuit = Circuit("AA-BB-CC-DD-EE-FF")
        circuit.mul()  # mul0
        m1 = circuit.mul()  # mul1
        identity = getattr(m1, id_input).id()
        i0 = circuit.int()
        circuit.connect(identity, i0, weight=1.0)

        with pytest.warns(UserWarning, match="(?i)shadow|constant.*giver|identity"):
            circuit.const(value=1.0)

    def test_const_without_identity_no_warning(self):
        """Allocating a constant with no Identity connected emits no warning."""
        circuit = Circuit("AA-BB-CC-DD-EE-FF")

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            circuit.const(value=1.0)
            shadowing_warnings = [
                x for x in w
                if issubclass(x.category, UserWarning)
                and "shadow" in str(x.message).lower()
            ]
            assert len(shadowing_warnings) == 0, (
                f"const() without identity should not trigger shadowing warning, "
                f"got: {[str(x.message) for x in shadowing_warnings]}"
            )


class TestCircuitOwnership:
    """Tests for circuit UUID ownership checks.

    Each Circuit generates a UUID at creation time and propagates it to all
    elements.  connect() must reject elements from a different circuit.
    """

    def test_elements_carry_circuit_id(self):
        circuit = Circuit("AA-BB-CC-DD-EE-FF")
        i0 = circuit.int()
        m0 = circuit.mul()
        id0 = m0.a.id()
        c0 = circuit.const()
        inp = circuit.input()
        out = circuit.output()

        for elem in [i0, m0, id0, c0, inp, out]:
            assert hasattr(elem, '_circuit_id'), (
                f"{type(elem).__name__} must have a _circuit_id attribute"
            )
            assert elem._circuit_id == circuit._circuit_id, (
                f"{type(elem).__name__}._circuit_id should match its circuit"
            )

    def test_mulinput_inherits_circuit_id(self):
        circuit = Circuit("AA-BB-CC-DD-EE-FF")
        m0 = circuit.mul()

        assert m0.a._circuit_id == circuit._circuit_id, (
            "Multiplier.a should carry the circuit's _circuit_id"
        )
        assert m0.b._circuit_id == circuit._circuit_id, (
            "Multiplier.b should carry the circuit's _circuit_id"
        )

    def test_connect_cross_circuit_source_raises(self):
        circuit_a = Circuit("AA-BB-CC-DD-EE-FF")
        circuit_b = Circuit("AA-BB-CC-DD-EE-FF")

        i0_a = circuit_a.int()
        i1_b = circuit_b.int()

        with pytest.raises(ValueError, match="(?i)circuit|belong|different"):
            circuit_a.connect(i0_a, i1_b, weight=1.0)

    def test_connect_cross_circuit_target_raises(self):
        circuit_a = Circuit("AA-BB-CC-DD-EE-FF")
        circuit_b = Circuit("AA-BB-CC-DD-EE-FF")

        i0_b = circuit_b.int()
        i1_a = circuit_a.int()

        with pytest.raises(ValueError, match="(?i)circuit|belong|different"):
            circuit_a.connect(i0_b, i1_a, weight=1.0)

    def test_probe_cross_circuit_source_raises(self):
        circuit_a = Circuit("AA-BB-CC-DD-EE-FF")
        circuit_b = Circuit("AA-BB-CC-DD-EE-FF")

        i0_b = circuit_b.int()

        with pytest.raises(ValueError, match="(?i)circuit|belong|different"):
            circuit_a.probe(i0_b)

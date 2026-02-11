# Copyright (c) 2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
Unit tests for element allocation in the new Circuit class.

These tests verify that the Circuit class correctly allocates computing
elements (integrators, multipliers, identities, constants, inputs, outputs)
using greedy allocation, returns properly typed wrapper dataclasses, and
raises ValueError on resource exhaustion.

Written as TDD tests before the Circuit class rewrite.
"""

import pytest

from pybrid.lucipy.circuits import (
    Circuit,
    Integrator,
    Multiplier,
    Identity,
    Constant,
    Input,
    Output,
)


class TestIntegratorAllocation:
    """Tests for Circuit.int() integrator allocation."""

    def test_allocate_integrator(self):
        """Circuit.int() returns an Integrator with valid id and lane."""
        circuit = Circuit()
        i0 = circuit.int()

        assert isinstance(i0, Integrator), (
            "int() must return an Integrator instance"
        )
        assert 0 <= i0.id <= 7, (
            f"Integrator id must be in range 0-7, got {i0.id}"
        )
        assert i0.lane == i0.id, (
            f"Integrator lane must equal its id (M0 block offset=0), "
            f"got lane={i0.lane} for id={i0.id}"
        )

    def test_allocate_integrator_with_ic(self):
        """Circuit.int(ic=0.5) sets the initial condition on the internal pybrid object."""
        circuit = Circuit()
        i0 = circuit.int(ic=0.5)

        assert isinstance(i0, Integrator), (
            "int(ic=0.5) must return an Integrator instance"
        )

        # Verify IC was set on the pybrid MIntBlock
        lucidac = circuit.to_computer()
        cluster = lucidac.entities[0].clusters[0]
        m0 = cluster.m0block

        assert m0.elements[i0.id].computation.ic == pytest.approx(0.5), (
            f"Integrator {i0.id} IC should be 0.5, "
            f"got {m0.elements[i0.id].computation.ic}"
        )

    def test_allocate_all_integrators(self):
        """Allocating 8 integrators yields distinct ids covering 0-7."""
        circuit = Circuit()
        integrators = [circuit.int() for _ in range(8)]

        ids = [i.id for i in integrators]
        assert len(set(ids)) == 8, (
            f"All 8 integrator ids must be distinct, got {ids}"
        )
        assert set(ids) == set(range(8)), (
            f"Integrator ids must cover 0-7, got {sorted(ids)}"
        )

    def test_allocate_integrator_overflow(self):
        """The 9th int() call must raise ValueError."""
        circuit = Circuit()
        for _ in range(8):
            circuit.int()

        with pytest.raises(ValueError, match="(?i)integrat|free|occupied|element"):
            circuit.int()


class TestMultiplierAllocation:
    """Tests for Circuit.mul() multiplier allocation."""

    def test_allocate_multiplier(self):
        """Circuit.mul() returns a Multiplier with valid id."""
        circuit = Circuit()
        m0 = circuit.mul()

        assert isinstance(m0, Multiplier), (
            "mul() must return a Multiplier instance"
        )
        assert 0 <= m0.id <= 3, (
            f"Multiplier id must be in range 0-3, got {m0.id}"
        )
        assert m0.lane == 8 + m0.id, (
            f"Multiplier lane must be 8 + id (M1 block offset), "
            f"got lane={m0.lane} for id={m0.id}"
        )

    def test_allocate_all_multipliers(self):
        """Allocating 4 multipliers yields distinct ids covering 0-3."""
        circuit = Circuit()
        multipliers = [circuit.mul() for _ in range(4)]

        ids = [m.id for m in multipliers]
        assert len(set(ids)) == 4, (
            f"All 4 multiplier ids must be distinct, got {ids}"
        )
        assert set(ids) == set(range(4)), (
            f"Multiplier ids must cover 0-3, got {sorted(ids)}"
        )

    def test_allocate_multiplier_overflow(self):
        """The 5th mul() call must raise ValueError."""
        circuit = Circuit()
        for _ in range(4):
            circuit.mul()

        with pytest.raises(ValueError, match="(?i)multipli|free|occupied|element"):
            circuit.mul()


class TestIdentityCreation:
    """Tests for _MulInput.id() identity element creation.

    Identity elements are created from multiplier inputs via m.a.id() / m.b.id().
    Only multipliers 0 and 1 have identity paths (M-block outputs 12-15).
    """

    def test_mul0_a_id_returns_identity_offset_0(self):
        """mul0.a.id() returns Identity(offset=0) for multiplier 0, input a."""
        circuit = Circuit()
        m0 = circuit.mul()
        id_a = m0.a.id()

        assert isinstance(id_a, Identity), (
            "m0.a.id() must return an Identity instance"
        )
        assert id_a.offset == 0, (
            f"mul0.a identity offset must be 0, got {id_a.offset}"
        )

    def test_mul0_b_id_returns_identity_offset_1(self):
        """mul0.b.id() returns Identity(offset=1) for multiplier 0, input b."""
        circuit = Circuit()
        m0 = circuit.mul()
        id_b = m0.b.id()

        assert isinstance(id_b, Identity), (
            "m0.b.id() must return an Identity instance"
        )
        assert id_b.offset == 1, (
            f"mul0.b identity offset must be 1, got {id_b.offset}"
        )

    def test_mul1_a_id_returns_identity_offset_2(self):
        """mul1.a.id() returns Identity(offset=2) for multiplier 1, input a."""
        circuit = Circuit()
        circuit.mul()  # mul0
        m1 = circuit.mul()  # mul1
        id_a = m1.a.id()

        assert isinstance(id_a, Identity), (
            "m1.a.id() must return an Identity instance"
        )
        assert id_a.offset == 2, (
            f"mul1.a identity offset must be 2, got {id_a.offset}"
        )

    def test_mul1_b_id_returns_identity_offset_3(self):
        """mul1.b.id() returns Identity(offset=3) for multiplier 1, input b."""
        circuit = Circuit()
        circuit.mul()  # mul0
        m1 = circuit.mul()  # mul1
        id_b = m1.b.id()

        assert isinstance(id_b, Identity), (
            "m1.b.id() must return an Identity instance"
        )
        assert id_b.offset == 3, (
            f"mul1.b identity offset must be 3, got {id_b.offset}"
        )

    def test_mul2_id_raises(self):
        """mul2.a.id() and mul2.b.id() raise ValueError (no identity path)."""
        circuit = Circuit()
        for _ in range(2):
            circuit.mul()
        m2 = circuit.mul()  # mul2, id=2

        with pytest.raises(ValueError, match="(?i)identity|path|multiplier"):
            m2.a.id()
        with pytest.raises(ValueError, match="(?i)identity|path|multiplier"):
            m2.b.id()

    def test_mul3_id_raises(self):
        """mul3.a.id() and mul3.b.id() raise ValueError (no identity path)."""
        circuit = Circuit()
        for _ in range(3):
            circuit.mul()
        m3 = circuit.mul()  # mul3, id=3

        with pytest.raises(ValueError, match="(?i)identity|path|multiplier"):
            m3.a.id()
        with pytest.raises(ValueError, match="(?i)identity|path|multiplier"):
            m3.b.id()

    def test_id_carries_circuit_id(self):
        """Identity from _MulInput.id() carries the creating circuit's _circuit_id."""
        circuit = Circuit()
        m0 = circuit.mul()
        id_a = m0.a.id()

        assert id_a._circuit_id == circuit._circuit_id, (
            "Identity._circuit_id should match its circuit"
        )

    def test_id_no_allocation_conflict_with_mul(self):
        """Identity coexists with multipliers — no mutual exclusion."""
        circuit = Circuit()
        m0 = circuit.mul()
        id0 = m0.a.id()

        assert isinstance(m0, Multiplier)
        assert isinstance(id0, Identity)
        assert id0.offset == 0, (
            "Identity offset=0 must work when multiplier slot 0 is occupied"
        )

    def test_id_same_input_multiple_times(self):
        """Calling .id() on the same _MulInput multiple times returns equivalent Identity."""
        circuit = Circuit()
        m0 = circuit.mul()
        id_a1 = m0.a.id()
        id_a2 = m0.a.id()

        assert id_a1 == id_a2, (
            "Repeated m0.a.id() calls must return equivalent Identity elements"
        )

    def test_circuit_id_method_raises(self):
        """Circuit.id() raises RuntimeError directing users to the new syntax."""
        circuit = Circuit()
        with pytest.raises(RuntimeError, match="(?i)removed|multiplier"):
            circuit.id(offset=0)

    def test_identity_method_removed(self):
        """The deprecated identity() method no longer exists."""
        circuit = Circuit()
        assert not hasattr(circuit, "identity"), (
            "identity() method should have been removed"
        )


class TestConstantAllocation:
    """Tests for Circuit.const() constant allocation."""

    def test_allocate_constant(self):
        """const() returns a Constant with a valid id."""
        circuit = Circuit()
        c0 = circuit.const()

        assert isinstance(c0, Constant), (
            "const() must return a Constant instance"
        )
        assert c0.id == 0, (
            f"First constant id should be 0, got {c0.id}"
        )

    def test_allocate_two_constants(self):
        """Two const() calls return Constant wrappers with distinct ids."""
        circuit = Circuit()
        c0 = circuit.const()
        c1 = circuit.const()

        assert c0.id != c1.id, (
            f"Two constants must have different ids, "
            f"got c0.id={c0.id}, c1.id={c1.id}"
        )

    def test_allocate_constant_overflow(self):
        """The 3rd const() call must raise ValueError."""
        circuit = Circuit()
        circuit.const()
        circuit.const()

        with pytest.raises(ValueError, match="(?i)constant|free|occupied|element"):
            circuit.const()


class TestInputOutputAllocation:
    """Tests for Circuit.input() and Circuit.output() ACL port allocation."""

    def test_allocate_input(self):
        """input() returns an Input with port 0 and lane in 24-31."""
        circuit = Circuit()
        inp = circuit.input()

        assert isinstance(inp, Input), (
            "input() must return an Input instance"
        )
        assert inp.port == 0, (
            f"First input port should be 0 (greedy), got {inp.port}"
        )
        assert 24 <= inp.lane <= 31, (
            f"Input lane must be in 24-31 (ACL range), got {inp.lane}"
        )

    def test_allocate_output(self):
        """output() returns an Output with port 0 and lane in 24-31."""
        circuit = Circuit()
        out = circuit.output()

        assert isinstance(out, Output), (
            "output() must return an Output instance"
        )
        assert out.port == 0, (
            f"First output port should be 0 (greedy), got {out.port}"
        )
        assert 24 <= out.lane <= 31, (
            f"Output lane must be in 24-31 (ACL range), got {out.lane}"
        )

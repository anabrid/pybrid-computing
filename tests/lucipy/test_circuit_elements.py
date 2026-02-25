# Copyright (c) 2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
Unit tests for element allocation in the new Circuit class.

These tests verify that the Circuit class correctly allocates computing
elements (integrators, multipliers, identities, constants, inputs, outputs)
using greedy allocation, returns properly typed wrapper dataclasses, and
raises ValueError on resource exhaustion.

Uses DummyDAC-independent unit tests; no hardware required.
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
        circuit = Circuit("AA-BB-CC-DD-EE-FF")
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
        circuit = Circuit("AA-BB-CC-DD-EE-FF")
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
        circuit = Circuit("AA-BB-CC-DD-EE-FF")
        integrators = [circuit.int() for _ in range(8)]

        ids = [i.id for i in integrators]
        assert len(set(ids)) == 8, (
            f"All 8 integrator ids must be distinct, got {ids}"
        )
        assert set(ids) == set(range(8)), (
            f"Integrator ids must cover 0-7, got {sorted(ids)}"
        )

    def test_allocate_integrator_overflow(self):
        circuit = Circuit("AA-BB-CC-DD-EE-FF")
        for _ in range(8):
            circuit.int()

        with pytest.raises(ValueError, match="(?i)integrat|free|occupied|element"):
            circuit.int()


class TestMultiplierAllocation:
    """Tests for Circuit.mul() multiplier allocation."""

    def test_allocate_multiplier(self):
        circuit = Circuit("AA-BB-CC-DD-EE-FF")
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
        circuit = Circuit("AA-BB-CC-DD-EE-FF")
        multipliers = [circuit.mul() for _ in range(4)]

        ids = [m.id for m in multipliers]
        assert len(set(ids)) == 4, (
            f"All 4 multiplier ids must be distinct, got {ids}"
        )
        assert set(ids) == set(range(4)), (
            f"Multiplier ids must cover 0-3, got {sorted(ids)}"
        )

    def test_allocate_multiplier_overflow(self):
        circuit = Circuit("AA-BB-CC-DD-EE-FF")
        for _ in range(4):
            circuit.mul()

        with pytest.raises(ValueError, match="(?i)multipli|free|occupied|element"):
            circuit.mul()


class TestIdentityCreation:
    """Tests for _MulInput.id() identity element creation.

    Identity elements are created from multiplier inputs via m.a.id() / m.b.id().
    Only multipliers 0 and 1 have identity paths (M-block outputs 12-15).
    """

    @pytest.mark.parametrize("mul_idx,input_name,expected_offset", [
        (0, "a", 0),
        (0, "b", 1),
        (1, "a", 2),
        (1, "b", 3),
    ])
    def test_identity_offset(self, mul_idx, input_name, expected_offset):
        """mul{idx}.{input}.id() returns Identity with the correct offset."""
        circuit = Circuit("AA-BB-CC-DD-EE-FF")
        muls = [circuit.mul() for _ in range(mul_idx + 1)]
        mul = muls[mul_idx]
        result = getattr(mul, input_name).id()

        assert isinstance(result, Identity), (
            f"mul{mul_idx}.{input_name}.id() must return an Identity instance"
        )
        assert result.offset == expected_offset, (
            f"mul{mul_idx}.{input_name} identity offset must be {expected_offset}, "
            f"got {result.offset}"
        )

    @pytest.mark.parametrize("mul_idx", [2, 3])
    def test_identity_raises_on_high_multiplier(self, mul_idx):
        circuit = Circuit("AA-BB-CC-DD-EE-FF")
        muls = [circuit.mul() for _ in range(mul_idx + 1)]
        mul = muls[mul_idx]

        with pytest.raises(ValueError, match="(?i)identity|path|multiplier"):
            mul.a.id()
        with pytest.raises(ValueError, match="(?i)identity|path|multiplier"):
            mul.b.id()

    def test_id_carries_circuit_id(self):
        circuit = Circuit("AA-BB-CC-DD-EE-FF")
        m0 = circuit.mul()
        id_a = m0.a.id()

        assert id_a._circuit_id == circuit._circuit_id, (
            "Identity._circuit_id should match its circuit"
        )

    def test_id_no_allocation_conflict_with_mul(self):
        circuit = Circuit("AA-BB-CC-DD-EE-FF")
        m0 = circuit.mul()
        id0 = m0.a.id()

        assert isinstance(m0, Multiplier)
        assert isinstance(id0, Identity)
        assert id0.offset == 0, (
            "Identity offset=0 must work when multiplier slot 0 is occupied"
        )

    def test_id_same_input_multiple_times(self):
        circuit = Circuit("AA-BB-CC-DD-EE-FF")
        m0 = circuit.mul()
        id_a1 = m0.a.id()
        id_a2 = m0.a.id()

        assert id_a1 == id_a2, (
            "Repeated m0.a.id() calls must return equivalent Identity elements"
        )

    def test_circuit_id_method_raises(self):
        circuit = Circuit("AA-BB-CC-DD-EE-FF")
        with pytest.raises(RuntimeError, match="(?i)removed|multiplier"):
            circuit.id(offset=0)


class TestConstantAllocation:
    """Tests for Circuit.const() constant allocation."""

    def test_allocate_constant(self):
        circuit = Circuit("AA-BB-CC-DD-EE-FF")
        c0 = circuit.const()

        assert isinstance(c0, Constant), (
            "const() must return a Constant instance"
        )
        assert c0.id == 0, (
            f"First constant id should be 0, got {c0.id}"
        )

    def test_allocate_two_constants(self):
        circuit = Circuit("AA-BB-CC-DD-EE-FF")
        c0 = circuit.const()
        c1 = circuit.const()

        assert c0.id != c1.id, (
            f"Two constants must have different ids, "
            f"got c0.id={c0.id}, c1.id={c1.id}"
        )

    def test_allocate_constant_overflow(self):
        circuit = Circuit("AA-BB-CC-DD-EE-FF")
        circuit.const()
        circuit.const()

        with pytest.raises(ValueError, match="(?i)constant|free|occupied|element"):
            circuit.const()


class TestInputOutputAllocation:
    """Tests for Circuit.input() and Circuit.output() ACL port allocation."""

    @pytest.mark.parametrize("method,expected_type", [
        ("input", Input),
        ("output", Output),
    ])
    def test_allocate_acl_port(self, method, expected_type):
        """input()/output() returns the correct type with port 0 and lane in 24-31."""
        circuit = Circuit("AA-BB-CC-DD-EE-FF")
        result = getattr(circuit, method)()

        assert isinstance(result, expected_type), (
            f"{method}() must return a {expected_type.__name__} instance"
        )
        assert result.port == 0, (
            f"First {method} port should be 0 (greedy), got {result.port}"
        )
        assert 24 <= result.lane <= 31, (
            f"{method} lane must be in 24-31 (ACL range), got {result.lane}"
        )

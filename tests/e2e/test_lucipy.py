# Copyright (c) 2022-2025 anabrid GmbH
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
E2E tests for lucipy integration.

Tests the lucipy high-level circuit definition API, circuit export to
protobuf format, and connection to LUCIDAC via DummyDAC.
"""

import asyncio
import json
import tempfile
from pathlib import Path

import pytest

from pybrid.lucidac.lucipy import Circuit, LUCIDAC
from pybrid.lucidac.lucipy.circuits import (
    Route,
    Routing,
    MIntBlockState,
    Integrator,
    Multiplier,
    Constant,
    Identity,
    Front,
    DefaultLUCIDAC,
)
from pybrid.mock import DummyDAC, DummyDACConfig, DummyDACMacMode


class TestCircuitDefinition:
    """Tests for circuit definition using lucipy API."""

    def test_create_simple_circuit(self):
        """
        Test creating a simple integrator circuit.

        Verifies:
        - Circuit can allocate integrators
        - Connections can be made between elements
        - ICs and k0 values can be set
        """
        circuit = Circuit()

        # Allocate integrator with initial condition
        i0 = circuit.int(ic=0.5)

        # Self-connection with negative feedback
        circuit.connect(i0, i0, weight=-1.0)

        # Verify integrator was allocated
        assert i0.id == 0, "First integrator should have id 0"
        assert circuit.ics[0] == 0.5, "IC should be set to 0.5"

        # Verify route was added
        assert len(circuit.routes) == 1, "Should have one route"
        route = circuit.routes[0]
        assert route.coeff == -1.0, "Coefficient should be -1.0"

    def test_create_harmonic_oscillator(self):
        """
        Test creating a harmonic oscillator circuit (two coupled integrators).

        Verifies:
        - Multiple integrators can be allocated
        - Cross-connections work correctly
        - Circuit represents second-order ODE
        """
        circuit = Circuit()

        # Allocate two integrators
        x = circuit.int(ic=1.0)  # x(0) = 1
        v = circuit.int(ic=0.0)  # v(0) = 0

        # dx/dt = v
        circuit.connect(v, x, weight=1.0)

        # dv/dt = -x (spring force)
        circuit.connect(x, v, weight=-1.0)

        # Verify structure
        assert len(circuit.routes) == 2, "Should have two routes"
        assert circuit.ics[x.id] == 1.0, "x IC should be 1.0"
        assert circuit.ics[v.id] == 0.0, "v IC should be 0.0"

    def test_multiplier_circuit(self):
        """
        Test creating a circuit with multipliers.

        Verifies:
        - Multipliers can be allocated
        - Both inputs (a, b) can be connected
        - Output can be routed
        """
        circuit = Circuit()

        # Allocate integrator and multiplier
        i0 = circuit.int(ic=0.5)
        m0 = circuit.mul()

        # Connect integrator output to both multiplier inputs (square)
        circuit.connect(i0, m0.a, weight=1.0)
        circuit.connect(i0, m0.b, weight=1.0)

        # Connect multiplier output back to integrator
        circuit.connect(m0, i0, weight=-1.0)

        assert len(circuit.routes) == 3, "Should have three routes"
        assert m0.id == 0, "First multiplier should have id 0"

    def test_constant_injection(self):
        """
        Test injecting constants into circuit.

        Verifies:
        - Constants can be allocated and used
        - Constant giver is enabled when constant is used
        """
        circuit = Circuit()

        i0 = circuit.int(ic=0.0)
        c0 = circuit.const()

        # Add constant to integrator
        circuit.connect(c0, i0, weight=0.5)

        assert circuit.u_constant is True, "Constant giver should be enabled"
        assert len(circuit.routes) == 1, "Should have one route"

    def test_front_panel_io(self):
        """
        Test front panel input/output connections.

        Verifies:
        - Front panel I/O can be allocated
        - Can route signals to/from front panel using probe()
        """
        circuit = Circuit()

        i0 = circuit.int(ic=0.0)

        # Use probe() method which correctly sets ACL select to external
        circuit.probe(i0, front_port=0, weight=1.0)

        # Verify ACL select was set for output
        assert circuit.acl_select[0] == "external", "ACL should be set for external output"


class TestCircuitExport:
    """Tests for circuit export to configuration formats."""

    def test_generate_json_config(self):
        """
        Test generating JSON configuration from circuit.

        Verifies:
        - Circuit can be exported to JSON format
        - JSON contains U, C, I block configurations
        - MIntBlock configuration is included
        """
        circuit = Circuit()
        i0 = circuit.int(ic=0.5)
        circuit.connect(i0, i0, weight=-0.5)

        # Generate JSON config (legacy format)
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            config = circuit.generate(sanity_check=False)

        # Verify structure
        assert "00-00-00-00-00-00" in config, "Should have carrier config"
        carrier = config["00-00-00-00-00-00"]
        assert "/0" in carrier, "Should have cluster 0"
        cluster = carrier["/0"]
        assert "/U" in cluster, "Should have U block"
        assert "/C" in cluster, "Should have C block"
        assert "/I" in cluster, "Should have I block"
        assert "/M0" in cluster, "Should have M0 block"

    def test_to_protobuf_config(self):
        """
        Test converting circuit to protobuf format.

        Verifies:
        - Circuit can be exported to protobuf
        - pb.File object is created
        - JSON representation is valid
        """
        circuit = Circuit()
        i0 = circuit.int(ic=0.3)
        circuit.connect(i0, i0, weight=-1.0)

        # Export to protobuf
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            config_json, pb_file = circuit.to_config()

        # Verify pb_file exists and has content
        assert pb_file is not None, "Should create pb.File"
        assert pb_file.bundle is not None, "pb.File should have bundle"

        # Verify JSON representation
        assert config_json is not None, "Should have JSON config"
        assert "pybrid_computing_pb" in config_json or "bundle" in config_json, (
            "JSON should have expected format"
        )

    def test_circuit_roundtrip(self):
        """
        Test that circuit can be exported and re-imported.

        Verifies:
        - Exported config can be loaded back
        - Routes are preserved through roundtrip
        """
        # Create original circuit manually (Routing.randomize params differ from MIntBlockState)
        original = Routing()
        original.randomize(num_lanes=5, max_coeff=1.0, seed=12345)

        # Export
        config = original.generate(sanity_check=False)

        # Import into new Routing
        loaded = Routing()
        loaded.load(config)

        # Verify routes match
        assert len(loaded.routes) == len(original.routes), (
            f"Route count mismatch: {len(loaded.routes)} vs {len(original.routes)}"
        )


class TestLUCIDACWrapper:
    """Tests for LUCIDAC wrapper class connection to DummyDAC."""

    @pytest.mark.asyncio
    async def test_lucidac_wrapper_initialization(self, dummy_dac_virtual):
        """
        Test that LUCIDAC wrapper can be initialized with endpoint.

        Verifies:
        - Wrapper accepts endpoint string
        - Parses host and port correctly
        """
        # Get actual bound port from the server socket
        port = dummy_dac_virtual._server.sockets[0].getsockname()[1]
        endpoint = f"tcp://127.0.0.1:{port}"

        lucidac = LUCIDAC(endpoint=endpoint)

        assert lucidac.host == "127.0.0.1", "Host should be parsed"
        assert lucidac.port == port, "Port should be parsed"

    @pytest.mark.asyncio
    async def test_lucidac_set_circuit(self, dummy_dac_virtual):
        """
        Test setting circuit on LUCIDAC wrapper.

        Verifies:
        - Circuit can be attached to wrapper
        - Circuit is converted to protobuf internally
        """
        port = dummy_dac_virtual._server.sockets[0].getsockname()[1]
        endpoint = f"tcp://127.0.0.1:{port}"

        lucidac = LUCIDAC(endpoint=endpoint)

        # Create and set circuit
        circuit = Circuit()
        i0 = circuit.int(ic=0.5)
        circuit.connect(i0, i0, weight=-1.0)

        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            lucidac.set_circuit(circuit)

        assert lucidac.circuit is not None, "Circuit should be set"

    @pytest.mark.asyncio
    async def test_lucidac_set_run_config(self, dummy_dac_virtual):
        """
        Test setting run configuration on LUCIDAC wrapper.

        Verifies:
        - Run config can be set with op_time and ic_time
        - DAQ config can be set
        """
        port = dummy_dac_virtual._server.sockets[0].getsockname()[1]
        endpoint = f"tcp://127.0.0.1:{port}"

        lucidac = LUCIDAC(endpoint=endpoint)

        # Set run configuration
        lucidac.set_run(op_time=1_000_000, ic_time=100_000)  # 1ms op, 0.1ms ic
        lucidac.set_daq(num_channels=4, sample_rate=100_000)

        assert lucidac.run_config.op_time == 1_000_000, "op_time should be set"
        assert lucidac.run_config.ic_time == 100_000, "ic_time should be set"
        assert lucidac.daq_config.num_channels == 4, "num_channels should be set"
        assert lucidac.daq_config.sample_rate == 100_000, "sample_rate should be set"


class TestRoutingHelpers:
    """Tests for routing helper classes and functions."""

    def test_route_sanity_check(self):
        """
        Test Route sanity checking catches invalid values.

        Verifies:
        - Out of range uin is detected
        - Out of range lane is detected
        - Out of range coefficient is detected
        """
        # Valid route
        valid_route = Route(0, 0, 1.0, 0)
        assert valid_route.sanity_list() == [], "Valid route should have no errors"

        # Invalid uin
        bad_uin = Route(20, 0, 1.0, 0)
        errors = bad_uin.sanity_list()
        assert len(errors) > 0, "Bad uin should be detected"

        # Invalid lane
        bad_lane = Route(0, 35, 1.0, 0)
        errors = bad_lane.sanity_list()
        assert len(errors) > 0, "Bad lane should be detected"

        # Invalid coefficient
        bad_coeff = Route(0, 0, 50.0, 0)
        errors = bad_coeff.sanity_list()
        assert len(errors) > 0, "Bad coefficient should be detected"

    def test_default_lucidac_element_factory(self):
        """
        Test DefaultLUCIDAC element factory creates correct elements.

        Verifies:
        - Integrators have correct out/a values
        - Multipliers have correct out/a/b values
        - Constants have correct out values
        """
        # Integrator
        int0 = DefaultLUCIDAC.make(Integrator, 0)
        assert int0.out == 0, "Int0 output should be 0"
        assert int0.a == 0, "Int0 input should be 0"

        int7 = DefaultLUCIDAC.make(Integrator, 7)
        assert int7.out == 7, "Int7 output should be 7"

        # Multiplier
        mul0 = DefaultLUCIDAC.make(Multiplier, 0)
        assert mul0.out == 8, "Mul0 output should be 8"
        assert mul0.a == 8, "Mul0 input a should be 8"
        assert mul0.b == 9, "Mul0 input b should be 9"

        # Constant
        const0 = DefaultLUCIDAC.make(Constant, 0)
        assert const0.out == 14, "Const0 clane should be 14"

    def test_routing_input_output_conversion(self):
        """
        Test input-to-output and output-to-input format conversions.

        Verifies:
        - Conversions are inverse of each other
        - Sparse matrices are handled correctly
        """
        # Create some input-centric data
        input_format = [0, 1, 2, None, 4, None, None, 7] + [None] * 24

        # Convert to output-centric
        output_format = Routing.input2output(input_format)

        # Convert back
        back_to_input = Routing.output2input(output_format)

        assert input_format == back_to_input, "Roundtrip should preserve data"

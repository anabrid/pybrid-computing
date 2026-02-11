# Copyright (c) 2022-2025 anabrid GmbH
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
E2E tests for lucipy integration.

Tests the lucipy high-level circuit definition API, circuit export to
protobuf format, and connection to LUCIDAC via DummyDAC.
"""

import asyncio
import json
import logging
import warnings
import tempfile
from pathlib import Path

import pytest

# DummyDAC returns a smaller data array than real hardware for the OP_END
# final-values callback. The controller's handle_run_data_end tries to
# index beyond that array, causing an IndexError that the protocol layer
# catches and logs at ERROR level (protocol.py:189-195).  The error is
# harmless — streamed run data arrives correctly — so we suppress the
# protocol logger during tests that execute actual runs against DummyDAC.
_PROTOCOL_LOGGER = "pybrid.redac.protocol.protocol"

from pybrid.lucipy import Circuit, LUCIDAC
from pybrid.lucipy.circuits import (
    Integrator,
    Multiplier,
    Constant,
    Identity,
    Input,
    Output,
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
        - ICs and k0 values can be set on the internal pybrid object
        """
        circuit = Circuit()

        # Allocate integrator with initial condition
        i0 = circuit.int(ic=0.5)

        # Self-connection with negative feedback
        circuit.connect(i0, i0, weight=-1.0)

        # Verify integrator was allocated
        assert i0.id == 0, "First integrator should have id 0"

        # Verify IC was set on the internal pybrid MIntBlock
        lucidac = circuit.to_computer()
        cluster = lucidac.entities[0].clusters[0]
        assert cluster.m0block.elements[0].computation.ic == pytest.approx(0.5), (
            "IC should be set to 0.5 on the internal pybrid object"
        )

        # Verify connection was made (UBlock has a lane pointing to i0)
        allocated_lanes = [
            lane for lane in range(24)
            if cluster.ublock.outputs[lane] == i0.lane
        ]
        assert len(allocated_lanes) == 1, "Should have one lane allocated for the connection"

        # Verify CBlock coefficient on that lane
        lane = allocated_lanes[0]
        c_factor = cluster.cblock.elements[lane].computation.factor
        assert c_factor == pytest.approx(-1.0), "Coefficient should be -1.0"

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

        # Verify ICs via internal pybrid object
        lucidac = circuit.to_computer()
        cluster = lucidac.entities[0].clusters[0]
        assert cluster.m0block.elements[x.id].computation.ic == pytest.approx(1.0), (
            "x IC should be 1.0"
        )
        assert cluster.m0block.elements[v.id].computation.ic == pytest.approx(0.0), (
            "v IC should be 0.0"
        )

        # Verify two connections exist (two lanes allocated)
        lanes_v_to_x = [
            lane for lane in range(24)
            if cluster.ublock.outputs[lane] == v.lane
        ]
        lanes_x_to_v = [
            lane for lane in range(24)
            if cluster.ublock.outputs[lane] == x.lane
        ]
        assert len(lanes_v_to_x) == 1, "Should have one lane for v->x connection"
        assert len(lanes_x_to_v) == 1, "Should have one lane for x->v connection"

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

        # Verify via pybrid object that 3 lanes were allocated
        lucidac = circuit.to_computer()
        cluster = lucidac.entities[0].clusters[0]

        used_lanes = [
            lane for lane in range(24)
            if cluster.ublock.outputs[lane] is not None
        ]
        assert len(used_lanes) == 3, "Should have three lanes allocated"
        assert m0.id == 0, "First multiplier should have id 0"

    def test_constant_injection(self):
        """
        Test injecting constants into circuit.

        Verifies:
        - Constants can be allocated and used
        - Connection with constant weight is properly set up
        """
        circuit = Circuit()

        i0 = circuit.int(ic=0.0)
        c0 = circuit.const()

        # Add constant to integrator
        circuit.connect(c0, i0, weight=0.5)

        # Verify via pybrid object
        lucidac = circuit.to_computer()
        cluster = lucidac.entities[0].clusters[0]

        # Find the lane used for the constant connection (output 14 or 15)
        allocated_lanes = [
            lane for lane in range(32)
            if cluster.ublock.outputs[lane] in (14, 15)
        ]
        assert len(allocated_lanes) == 1, "Should have one lane for constant connection"

        # Verify M-block output matches lane range
        lane = allocated_lanes[0]
        expected_output = 15 if lane < 16 else 14
        assert cluster.ublock.outputs[lane] == expected_output

    def test_front_panel_io(self):
        """
        Test front panel input/output connections.

        Verifies:
        - Front panel I/O can be allocated
        - Can route signals to/from front panel using probe()
        """
        circuit = Circuit()

        i0 = circuit.int(ic=0.0)

        # Use probe() method which allocates an output and connects
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            circuit.probe(i0, front_port=0, weight=1.0)

        # Verify via pybrid object that ACL_OUT lane 24 has source i0
        lucidac = circuit.to_computer()
        cluster = lucidac.entities[0].clusters[0]
        assert cluster.ublock.outputs[24] == i0.lane, (
            "UBlock at ACL lane 24 should point to integrator output"
        )


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

    def test_generate_json_is_serializable(self):
        """
        Test that generate() output can be passed to json.dumps().

        This is the pattern used by examples/lucipy/decay.py.
        """
        circuit = Circuit()
        i0 = circuit.int(ic=-0.8, slow=True)
        circuit.connect(i0, i0, weight=0.3)
        circuit.measure(i0, adc_channel=0)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            config = circuit.generate()

        # Must not raise
        json_str = json.dumps(config, indent=2, default=str)
        assert len(json_str) > 0, "JSON output should not be empty"

        # Verify key structure survives roundtrip
        parsed = json.loads(json_str)
        assert "00-00-00-00-00-00" in parsed

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


class TestLUCIDACWrapper:
    """Tests for LUCIDAC wrapper class connection to DummyDAC."""

    @pytest.mark.asyncio
    async def test_lucidac_wrapper_initialization(self, dummy_dac_virtual):
        """
        Test that LUCIDAC wrapper can be initialized with endpoint.

        Verifies:
        - Wrapper accepts endpoint string
        - Initialization succeeds without errors
        """
        # Get actual bound port from the server socket
        port = dummy_dac_virtual._server.sockets[0].getsockname()[1]
        endpoint = f"tcp://127.0.0.1:{port}"

        # Should accept endpoint as positional argument
        lucidac = LUCIDAC(endpoint)

        # Verify it created internal structures
        assert lucidac._num_devices == 1, "Should have one device registered"

    @pytest.mark.asyncio
    async def test_lucidac_set_circuit(self, dummy_dac_virtual):
        """
        Test setting circuit on LUCIDAC wrapper.

        Verifies:
        - Circuit can be attached to wrapper
        - set_circuit() succeeds without errors
        """
        port = dummy_dac_virtual._server.sockets[0].getsockname()[1]
        endpoint = f"tcp://127.0.0.1:{port}"

        lucidac = LUCIDAC(endpoint)

        # Create and set circuit
        circuit = Circuit()
        i0 = circuit.int(ic=0.5)
        circuit.connect(i0, i0, weight=-1.0)

        # Should succeed without errors
        lucidac.set_circuit(circuit)

        # Verify circuit is stored in pool (device 0)
        stored_circuit = lucidac._circuits[0]
        assert stored_circuit is not None, "Circuit should be stored in pool"

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

        lucidac = LUCIDAC(endpoint)

        # Set run configuration (should succeed without errors)
        lucidac.set_run(op_time=1_000_000, ic_time=100_000)  # 1ms op, 0.1ms ic
        lucidac.set_daq(num_channels=4, sample_rate=100_000)

        # Verify configs are stored internally
        assert lucidac._run_config.op_time == 1_000_000, "op_time should be set"
        assert lucidac._run_config.ic_time == 100_000, "ic_time should be set"
        assert lucidac._daq_config.num_channels == 4, "num_channels should be set"
        assert lucidac._daq_config.sample_rate == 100_000, "sample_rate should be set"


class TestLUCIStackE2E:
    """E2E tests for LUCIStack set-and-run workflow against DummyDAC."""

    @pytest.mark.asyncio
    async def test_lucistack_set_and_run_against_dummy(self):
        """
        Full end-to-end workflow: create circuit, configure, and run
        against a DummyDAC in LUCIDAC mode.

        Verifies:
        - LUCIStack can be initialized from an endpoint string
        - Circuit can be set on the stack
        - DAQ and run config can be applied
        - _run() executes successfully against DummyDAC
        - A Run object is returned with data
        """
        from tests.conftest import get_test_port

        config = DummyDACConfig(lucidac_mode=True)
        port = get_test_port(10)

        async with DummyDAC("127.0.0.1", port, config) as dac:
            dac_port = dac._server.sockets[0].getsockname()[1]
            endpoint = f"tcp://127.0.0.1:{dac_port}"

            # Create LUCIStack from endpoint
            luci = LUCIDAC(endpoint)

            # Build a simple decay circuit: dx/dt = -x, x(0) = 1.0
            circuit = Circuit()
            i0 = circuit.int(ic=1.0)
            circuit.connect(i0, i0, weight=-1.0)
            circuit.measure(i0, adc_channel=0)

            # Set circuit, DAQ, and run config
            luci.set_circuit(circuit)
            luci.set_daq(num_channels=1, sample_rate=1000)
            luci.set_run(
                ic_time=100_000,     # 100 us
                op_time=10_000_000   # 10 ms
            )

            # Suppress protocol logger — see _PROTOCOL_LOGGER comment above.
            logging.getLogger(_PROTOCOL_LOGGER).setLevel(logging.CRITICAL)
            try:
                run = await luci._run()
            finally:
                logging.getLogger(_PROTOCOL_LOGGER).setLevel(logging.NOTSET)

            assert run is not None, "run() should return a Run object"
            assert hasattr(run, "data"), "Run should have a data attribute"


class TestLorenz96Pattern:
    """E2E test replicating examples/lucipy/lorenz96.py circuit definition."""

    def test_lorenz96_example_pattern(self):
        """
        Replicate the Lorenz 96 example pattern from examples/lucipy/lorenz96.py.

        The Lorenz 96 circuit uses:
        - N=4 integrators (slow mode)
        - N=4 multipliers
        - 1 constant source
        - Cross-coupling connections between integrators via multipliers
        - Constant forcing term injected into each integrator
        - 4 ADC measure channels

        Verifies:
        - Circuit compiles without error
        - All elements are allocated correctly
        - to_config() produces valid protobuf output
        - to_computer() returns a valid LUCIDAC with expected block state
        """
        N = 4
        circuit = Circuit()

        x = []
        m = []
        for i in range(N):
            x.append(circuit.int(slow=True))
            m.append(circuit.mul())

        F = circuit.const()

        for i in range(N):
            # Multiplier a-input: x[i-1]
            circuit.connect(x[i - 1], m[i].a, weight=-1.0)

            # Multiplier b-input: x[i-2] and x[i-3]
            circuit.connect(x[i - 2], m[i].b, weight=+1.0)
            circuit.connect(x[i - 3], m[i].b, weight=-1.0)

            # Multiplier output to integrator
            circuit.connect(m[i], x[i], weight=-0.666 * 3 - 0.1)

            # Constant forcing term
            circuit.connect(F, x[i], weight=-0.10)

            # Measure each integrator
            circuit.measure(x[i], adc_channel=i)

        # Verify element allocation counts
        integrators_allocated = sum(1 for used in circuit._integrators_used if used)
        assert integrators_allocated == N, (
            f"Should have {N} integrators allocated, got {integrators_allocated}"
        )

        muls_allocated = sum(
            int(state) for state in circuit._multipliers_used
        )
        assert muls_allocated == N, (
            f"Should have {N} multipliers allocated, got {muls_allocated}"
        )

        constants_allocated = circuit._constants_allocated
        assert constants_allocated == 1, (
            f"Should have 1 constant allocated, got {constants_allocated}"
        )

        adc_assigned = sum(1 for ch in circuit._adc_channels if ch is not None)
        assert adc_assigned == N, (
            f"Should have {N} ADC channels assigned, got {adc_assigned}"
        )

        # Verify to_computer() returns valid LUCIDAC
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            lucidac = circuit.to_computer()

        cluster = lucidac.entities[0].clusters[0]

        # Check integrator ICs are default (0.0) and slow mode (k=100)
        for i in range(N):
            elem = cluster.m0block.elements[i]
            assert elem.computation.ic == pytest.approx(0.0), (
                f"Integrator {i} IC should be 0.0 (default)"
            )
            assert elem.computation.k == 100, (
                f"Integrator {i} should be slow mode (k=100)"
            )

        # Verify to_config() produces valid protobuf
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            config_json, pb_file = circuit.to_config()

        assert pb_file is not None, "to_config() should produce a pb.File"
        assert pb_file.bundle is not None, "pb.File should have a config bundle"
        assert config_json is not None, "to_config() should produce JSON config"

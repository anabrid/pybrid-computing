# Copyright (c) 2022-2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
Basic hardware validation tests for LUCIDAC, REDAC and Simulator devices.

These tests verify fundamental connectivity and basic operations
on real hardware. They require TEST_LUCIDAC_ENDPOINT, TEST_REDAC_ENDPOINT,
and/or TEST_SIMULATOR_ENDPOINT environment variables to be set.

Environment Variables:
    TEST_LUCIDAC_ENDPOINT: tcp://host:port for LUCIDAC connection
    TEST_REDAC_ENDPOINT: tcp://host:port for REDAC connection
    TEST_SIMULATOR_ENDPOINT: tcp://host:port for Simulator connection
"""

import asyncio
from uuid import uuid4

import pytest

from pybrid.redac.controller import Controller as REDACController
from pybrid.redac.run import Run, RunConfig, RunState
from pybrid.sim.controller import Controller as SimController
from tests.conftest import get_device_endpoint, simulator_endpoint


@pytest.fixture
def lucidac_endpoint():
    """
    Fixture providing LUCIDAC endpoint from TEST_LUCIDAC_ENDPOINT.

    Skips test if environment variable is not set.

    Returns:
        Tuple of (hostname, port) for LUCIDAC connection.
    """
    endpoint = get_device_endpoint("TEST_LUCIDAC_ENDPOINT")
    if endpoint is None:
        pytest.skip("TEST_LUCIDAC_ENDPOINT not set")
    return endpoint


@pytest.fixture
def redac_endpoint():
    """
    Fixture providing REDAC endpoint from TEST_REDAC_ENDPOINT.

    Skips test if environment variable is not set.

    Returns:
        Tuple of (hostname, port) for REDAC connection.
    """
    endpoint = get_device_endpoint("TEST_REDAC_ENDPOINT")
    if endpoint is None:
        pytest.skip("TEST_REDAC_ENDPOINT not set")
    return endpoint


@pytest.mark.device
@pytest.mark.lucidac
class TestLUCIDACBasic:

    async def test_connection(self, lucidac_endpoint):
        host, port = lucidac_endpoint

        async with REDACController() as ctrl:
            await ctrl.add_device(host, port)

            assert len(ctrl.devices) >= 1, (
                "Controller should have at least one device registered"
            )
            assert len(ctrl.protocols) >= 1, (
                "Controller should have at least one protocol active"
            )

    async def test_describe(self, lucidac_endpoint):
        host, port = lucidac_endpoint

        async with REDACController() as ctrl:
            await ctrl.add_device(host, port)

            # Get all device paths
            device_paths = list(ctrl.devices.keys())
            assert len(device_paths) >= 1, "Should have device paths"

            # Check that each device path is valid
            for path in device_paths:
                assert path is not None, "Device path should not be None"
                # LUCIDAC paths should have MAC address format at root
                root_path = path.to_root()
                assert root_path is not None, "Root path should exist"

            # Check computer structure was populated
            assert ctrl.computer is not None, "Computer should be initialized"
            assert len(ctrl.computer.carriers) >= 1, (
                "Computer should have at least one carrier"
            )

    async def test_simple_run(self, lucidac_endpoint):
        host, port = lucidac_endpoint

        async with REDACController() as ctrl:
            await ctrl.add_device(host, port)

            # Create a minimal run (very short op_time)
            run = Run(
                id_=uuid4(),
                config=RunConfig(
                    ic_time=10_000,      # 10us IC time
                    op_time=100_000,     # 100us OP time
                ),
            )

            # Start the run
            run_state = await ctrl.start_run(run)

            # Verify run state tracking was set up
            involved_paths = list(run_state.get_involved_paths())
            assert len(involved_paths) >= 1, (
                "Run should involve at least one device path"
            )

            # Wait for run to complete (with timeout)
            try:
                async with asyncio.timeout(10.0):
                    await run_state.wait_all(RunState.DONE)
            except asyncio.TimeoutError:
                reached_done, not_done = run_state.status(RunState.DONE)
                pytest.fail(
                    f"Run did not complete within timeout. "
                    f"DONE reached: {len(reached_done)}/{len(involved_paths)}"
                )

    async def test_reset_device(self, lucidac_endpoint):
        host, port = lucidac_endpoint

        async with REDACController() as ctrl:
            await ctrl.add_device(host, port)

            initial_device_count = len(ctrl.devices)

            # Send reset command
            await ctrl.reset(keep_calibration=True, sync=False)

            # Verify controller state is still valid
            assert len(ctrl.devices) == initial_device_count, (
                "Device count should remain unchanged after reset"
            )


@pytest.mark.device
@pytest.mark.redac
class TestREDACBasic:

    async def test_connection(self, redac_endpoint):
        host, port = redac_endpoint

        async with REDACController() as ctrl:
            await ctrl.add_device(host, port)

            assert len(ctrl.devices) >= 1, (
                "Controller should have at least one device registered"
            )
            assert len(ctrl.protocols) >= 1, (
                "Controller should have at least one protocol active"
            )

    async def test_multi_carrier(self, redac_endpoint):
        host, port = redac_endpoint

        async with REDACController() as ctrl:
            await ctrl.add_device(host, port)

            # REDAC typically has multiple carriers
            num_devices = len(ctrl.devices)
            num_protocols = len(ctrl.protocols)

            assert num_devices >= 1, "Should have at least one carrier"

            # Verify protocol->path mapping consistency
            total_managed_paths = sum(
                len(paths) for paths in ctrl.protocols.values()
            )
            assert total_managed_paths == num_devices, (
                f"Protocol managed paths ({total_managed_paths}) should match "
                f"device count ({num_devices})"
            )

            # Verify computer carriers match devices
            assert len(ctrl.computer.carriers) == num_devices, (
                f"Computer carriers ({len(ctrl.computer.carriers)}) should "
                f"match device count ({num_devices})"
            )

    async def test_describe(self, redac_endpoint):
        host, port = redac_endpoint

        async with REDACController() as ctrl:
            await ctrl.add_device(host, port)

            # Check computer structure
            assert ctrl.computer is not None, "Computer should be initialized"

            for carrier in ctrl.computer.carriers:
                assert carrier.path is not None, "Carrier should have path"
                assert len(carrier.clusters) >= 0, (
                    "Carrier should have clusters list"
                )


def configure_harmonic_oscillator(computer):
    """
    Configure a simple harmonic oscillator circuit on the computer.

    Sets up a basic oscillator using two integrators:
    dx/dt = v, dv/dt = -x

    Args:
        computer: The computer (Simulator/REDAC) to configure.
    """
    if not computer.carriers:
        return

    carrier = computer.carriers[0]
    if not carrier.clusters:
        return

    cluster = carrier.clusters[0]

    # Configure CBlock coefficients for feedback
    # c[0] = -1.0 (for -x feedback), c[8] = 1.0 (for v)
    if cluster.cblock and cluster.cblock.elements:
        for elem in cluster.cblock.elements:
            elem.computation.factor = 0.0
        if len(cluster.cblock.elements) > 0:
            cluster.cblock.elements[0].computation.factor = -1.0
        if len(cluster.cblock.elements) > 8:
            cluster.cblock.elements[8].computation.factor = 1.0

    # Configure MIntBlock with initial conditions
    if cluster.m0block and cluster.m0block.elements:
        # First integrator: x, ic=0
        cluster.m0block.elements[0].ic = 0.0
        cluster.m0block.elements[0].k = 10000
        # Second integrator: v, ic=-0.42 (initial velocity)
        cluster.m0block.elements[1].ic = -0.42
        cluster.m0block.elements[1].k = 10000

    # Configure UBlock outputs (routing)
    if cluster.ublock:
        cluster.ublock.outputs = [None] * 32
        cluster.ublock.outputs[0] = 1  # Route integrator 1 output to lane 0
        cluster.ublock.outputs[8] = 0  # Route integrator 0 output to lane 8
        cluster.ublock.constant = True

    # Configure IBlock outputs (integrator inputs)
    if cluster.iblock:
        cluster.iblock.outputs = [[] for _ in range(16)]
        cluster.iblock.outputs[0] = [0]   # Integrator 0 input from lane 0
        cluster.iblock.outputs[1] = [8]   # Integrator 1 input from lane 8


@pytest.mark.device
@pytest.mark.sim
class TestSimulatorBasic:

    async def test_connection(self, simulator_endpoint):
        host, port = simulator_endpoint

        async with SimController() as ctrl:
            await ctrl.add_device(host, port)

            assert len(ctrl.devices) >= 1, (
                "Controller should have at least one device registered"
            )
            assert len(ctrl.protocols) >= 1, (
                "Controller should have at least one protocol active"
            )

    async def test_describe(self, simulator_endpoint):
        host, port = simulator_endpoint

        async with SimController() as ctrl:
            await ctrl.add_device(host, port)

            # Get all device paths
            device_paths = list(ctrl.devices.keys())
            assert len(device_paths) >= 1, "Should have device paths"

            # Check that each device path is valid
            for path in device_paths:
                assert path is not None, "Device path should not be None"
                # Simulator paths should have MAC address format at root
                root_path = path.to_root()
                assert root_path is not None, "Root path should exist"

            # Check computer structure was populated
            assert ctrl.computer is not None, "Computer should be initialized"
            assert len(ctrl.computer.carriers) >= 1, (
                "Computer should have at least one carrier"
            )

    async def test_simple_run(self, simulator_endpoint):
        host, port = simulator_endpoint

        async with SimController() as ctrl:
            await ctrl.add_device(host, port)

            # Configure a simple harmonic oscillator circuit
            configure_harmonic_oscillator(ctrl.computer)

            # Send configuration to simulator
            await ctrl.set_computer(ctrl.computer)

            # Create a minimal run (very short op_time)
            run = Run(
                id_=uuid4(),
                config=RunConfig(
                    ic_time=10_000,      # 10us IC time
                    op_time=100_000,     # 100us OP time
                ),
            )

            # Start the run
            run_state = await ctrl.start_run(run)

            # Verify run state tracking was set up
            involved_paths = list(run_state.get_involved_paths())
            assert len(involved_paths) >= 1, (
                "Run should involve at least one device path"
            )

            # Wait for run to complete (with timeout)
            try:
                async with asyncio.timeout(10.0):
                    await run_state.wait_all(RunState.DONE)
            except asyncio.TimeoutError:
                reached_done, not_done = run_state.status(RunState.DONE)
                pytest.fail(
                    f"Run did not complete within timeout. "
                    f"DONE reached: {len(reached_done)}/{len(involved_paths)}"
                )

    async def test_reset_device(self, simulator_endpoint):
        host, port = simulator_endpoint

        async with SimController() as ctrl:
            await ctrl.add_device(host, port)

            initial_device_count = len(ctrl.devices)

            # Send reset command
            await ctrl.reset(keep_calibration=True, sync=False)

            # Verify controller state is still valid
            assert len(ctrl.devices) == initial_device_count, (
                "Device count should remain unchanged after reset"
            )

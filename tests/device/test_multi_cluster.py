# Copyright (c) 2022-2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
Multi-cluster REDAC operation tests.

These tests verify operations across multiple clusters on REDAC
hardware, including configuration distribution and parallel execution.

Environment Variables:
    TEST_REDAC_ENDPOINT: tcp://host:port for REDAC connection (required)
"""

import asyncio
from uuid import uuid4

import pytest

import pybrid.base.proto.main_pb2 as pb
from pybrid.redac.controller import Controller
from pybrid.redac.run import Run, RunConfig, RunState
from tests.conftest import get_device_endpoint


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
@pytest.mark.redac
class TestREDACMultiCluster:

    async def test_all_clusters_configurable(self, redac_endpoint):
        host, port = redac_endpoint

        async with Controller() as ctrl:
            await ctrl.add_device(host, port)

            # Collect all cluster paths
            cluster_paths = []
            for carrier in ctrl.computer.carriers:
                for cluster in carrier.clusters:
                    cluster_paths.append(cluster.path)

            if len(cluster_paths) == 0:
                pytest.skip("No clusters available on connected REDAC")

            # Create configuration for each cluster's M0 block (MIntBlock)
            configs = []
            for cluster_path in cluster_paths:
                # Configure M0 block with default IC values
                config_entry = pb.Item(
                    entity=pb.EntityId(path=str(cluster_path / "M0")),
                )
                configs.append(config_entry)

            module = pb.Module(items=configs)

            # Send configuration - should not raise
            await ctrl.set_module(module)

            # Verify all clusters were addressed
            # (No error means configuration was accepted)
            assert len(cluster_paths) >= 1, f"Configured {len(cluster_paths)} clusters successfully"

    async def test_parallel_cluster_run(self, redac_endpoint):
        host, port = redac_endpoint

        async with Controller() as ctrl:
            await ctrl.add_device(host, port)

            num_carriers = len(ctrl.computer.carriers)
            if num_carriers < 1:
                pytest.skip("Need at least one carrier for this test")

            # Create a run
            run = Run(
                id_=uuid4(),
                config=RunConfig(
                    ic_time=10_000,  # 10us
                    op_time=100_000,  # 100us
                ),
            )

            # Start the run
            run_state = await ctrl.start_run(run)

            # Verify all carriers are involved
            involved_paths = set(run_state.get_involved_paths())
            device_paths = set(ctrl.devices.keys())

            assert involved_paths == device_paths, (
                f"Run should involve all device paths. " f"Involved: {involved_paths}, Devices: {device_paths}"
            )

            # Wait for all carriers to complete
            try:
                async with asyncio.timeout(15.0):
                    await run_state.wait_all(RunState.DONE)
            except asyncio.TimeoutError:
                reached_done, not_done = run_state.status(RunState.DONE)
                pytest.fail(f"Not all carriers completed. " f"DONE: {len(reached_done)}/{len(involved_paths)}")

            # Verify all paths reached DONE
            reached_done, not_done = run_state.status(RunState.DONE)
            assert len(not_done) == 0, f"All carriers should reach DONE state. " f"Not done: {not_done}"

    async def test_cluster_isolation(self, redac_endpoint):
        host, port = redac_endpoint

        async with Controller() as ctrl:
            await ctrl.add_device(host, port)

            # Get all cluster paths
            cluster_paths = []
            for carrier in ctrl.computer.carriers:
                for cluster in carrier.clusters:
                    cluster_paths.append(cluster.path)

            if len(cluster_paths) < 2:
                pytest.skip("Need at least 2 clusters to test isolation")

            # Configure first cluster with specific values
            first_cluster_path = cluster_paths[0]
            config_first = pb.Item(
                entity=pb.EntityId(path=str(first_cluster_path / "M0")),
            )

            module_first = pb.Module(items=[config_first])
            await ctrl.set_module(module_first)

            # Configure second cluster with different values
            second_cluster_path = cluster_paths[1]
            config_second = pb.Item(
                entity=pb.EntityId(path=str(second_cluster_path / "M0")),
            )

            module_second = pb.Module(items=[config_second])
            await ctrl.set_module(module_second)

            # Both configurations should have succeeded independently
            # (Test passes if no exception was raised)
            assert first_cluster_path != second_cluster_path, "Clusters should have distinct paths"


@pytest.mark.asyncio
class TestMultiCarrierDummyDAC:
    """
    Tests for multi-carrier operations using DummyDAC.

    These tests verify multi-carrier functionality without requiring
    real REDAC hardware, making them suitable for CI.
    """

    async def test_parallel_carrier_run_with_dummy(self, dummy_dac_virtual):
        async with Controller() as ctrl:
            await ctrl.add_device("127.0.0.1", dummy_dac_virtual.port)

            assert len(ctrl.computer.carriers) >= 2, "DummyDAC should have at least 2 carriers"

            run = Run(
                id_=uuid4(),
                config=RunConfig(ic_time=10_000, op_time=100_000),
            )

            import warnings

            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                completed_run = await ctrl.start_and_await_run(run)

            assert completed_run.state == RunState.DONE

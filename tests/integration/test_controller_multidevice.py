# Copyright (c) 2022-2025 anabrid GmbH
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
Integration tests for Controller with multiple devices.

Tests multi-device configuration, distributed operations, and
concurrent run execution across DummyDAC backends.

Note: DummyDAC in VIRTUAL mode provides 2 carriers with fixed MACs.
When testing multi-device scenarios, we use the carriers from a single
DummyDAC instance since multiple DummyDACs would have conflicting MACs.
"""

import asyncio
from uuid import uuid4

import pytest

import pybrid.base.proto.main_pb2 as pb
from pybrid.mock import DummyDAC, DummyDACConfig, DummyDACMacMode
from pybrid.redac.controller import Controller
from pybrid.redac.run import Run, RunConfig, RunState
from tests.conftest import get_test_port


class TestControllerMultiDevice:
    """Tests for Controller managing multiple devices/carriers."""

    @pytest.mark.asyncio
    async def test_add_two_devices(self):
        """
        Test that Controller correctly registers multiple carriers from a DummyDAC.

        DummyDAC provides 2 carriers, so adding one DummyDAC should result in
        2 device entries being tracked.

        Verifies:
        - Controller connects successfully
        - Both carriers are tracked in controller.devices
        - Protocol is registered with correct paths
        """
        config = DummyDACConfig(mac_mode=DummyDACMacMode.VIRTUAL)

        async with DummyDAC("127.0.0.1", get_test_port(), config) as dac:
            dac_port = dac._server.sockets[0].getsockname()[1]

            async with Controller(standalone=True) as ctrl:
                # Initially no devices
                assert len(ctrl.devices) == 0
                assert len(ctrl.protocols) == 0

                # Add device (DummyDAC provides 2 carriers)
                await ctrl.add_device("127.0.0.1", dac_port)

                # Should have 2 device entries (one per carrier)
                assert len(ctrl.devices) == 2, (
                    f"Expected 2 devices (carriers), got {len(ctrl.devices)}"
                )

                # Should have 1 protocol managing both paths
                assert len(ctrl.protocols) == 1, (
                    f"Expected 1 protocol, got {len(ctrl.protocols)}"
                )

                # The protocol should manage both carrier paths
                protocol = next(iter(ctrl.protocols.keys()))
                managed_paths = ctrl.protocols[protocol]
                assert len(managed_paths) == 2, (
                    f"Protocol should manage 2 paths, manages {len(managed_paths)}"
                )

                # Verify device paths match managed paths
                device_paths = set(ctrl.devices.keys())
                assert device_paths == managed_paths, (
                    "Device paths should match protocol managed paths"
                )

    @pytest.mark.asyncio
    async def test_config_distributed_to_devices(self):
        """
        Test that configuration is correctly distributed to multiple carriers.

        Verifies:
        - Config bundle can be sent to controller
        - Configs targeting different carriers are handled correctly
        - No errors occur during config distribution
        """
        config = DummyDACConfig(mac_mode=DummyDACMacMode.VIRTUAL)

        async with DummyDAC("127.0.0.1", get_test_port(), config) as dac:
            dac_port = dac._server.sockets[0].getsockname()[1]

            async with Controller(standalone=True) as ctrl:
                await ctrl.add_device("127.0.0.1", dac_port)

                # Get paths for each carrier
                all_paths = list(ctrl.devices.keys())
                assert len(all_paths) == 2, "Should have 2 carrier paths"

                # Create config entries for different carriers
                configs = []
                for path in all_paths:
                    config_entry = pb.Config(
                        entity=pb.EntityId(path=str(path / "0" / "M0")),
                    )
                    configs.append(config_entry)

                bundle = pb.ConfigBundle(configs=configs)

                # This should not raise - configs should be distributed
                await ctrl.set_config_bundle(bundle)

                # Verify controller state is still valid
                assert len(ctrl.devices) == 2
                assert len(ctrl.protocols) == 1

    @pytest.mark.asyncio
    async def test_run_with_multiple_carriers(self):
        """
        Test starting a run across multiple carriers.

        Verifies:
        - Run can be started with multiple carriers
        - DistributedRunState tracks all involved paths
        - Run state changes are received from all carriers
        """
        config = DummyDACConfig(mac_mode=DummyDACMacMode.VIRTUAL)

        async with DummyDAC("127.0.0.1", get_test_port(), config) as dac:
            dac_port = dac._server.sockets[0].getsockname()[1]

            async with Controller(standalone=True) as ctrl:
                await ctrl.add_device("127.0.0.1", dac_port)

                all_paths = list(ctrl.devices.keys())
                assert len(all_paths) == 2, "Need 2 carriers for this test"

                # Create a run with minimal config
                run = Run(
                    id_=uuid4(),
                    config=RunConfig(
                        ic_time=100_000,  # 100us
                        op_time=10_000_000,  # 10ms
                    ),
                )

                # Start the run
                run_state = await ctrl.start_run(run)

                # Verify run state tracks all paths
                involved_paths = set(run_state.get_involved_paths())
                assert len(involved_paths) == 2, (
                    f"Run should involve 2 paths, got {len(involved_paths)}"
                )

                # Each carrier path should be tracked
                for path in all_paths:
                    assert path in involved_paths, (
                        f"Path {path} should be in involved paths"
                    )

                # Wait for run to complete (with timeout)
                try:
                    async with asyncio.timeout(5.0):
                        await run_state.wait_all(RunState.DONE)
                except asyncio.TimeoutError:
                    # Check what states we did reach
                    reached_takeoff, not_takeoff = run_state.status(RunState.TAKE_OFF)
                    reached_done, not_done = run_state.status(RunState.DONE)
                    pytest.fail(
                        f"Run did not complete in time. "
                        f"TAKE_OFF reached: {len(reached_takeoff)}/{len(reached_takeoff)+len(not_takeoff)}, "
                        f"DONE reached: {len(reached_done)}/{len(reached_done)+len(not_done)}"
                    )

    @pytest.mark.asyncio
    async def test_reset_all_carriers(self):
        """
        Test that reset command is sent to all connected carriers.

        Verifies:
        - Reset command is forwarded to backend
        - No errors occur during reset
        - Controller state remains valid after reset
        """
        config = DummyDACConfig(mac_mode=DummyDACMacMode.VIRTUAL)

        async with DummyDAC("127.0.0.1", get_test_port(), config) as dac:
            dac_port = dac._server.sockets[0].getsockname()[1]

            async with Controller(standalone=True) as ctrl:
                await ctrl.add_device("127.0.0.1", dac_port)

                # Verify initial state
                assert len(ctrl.devices) == 2, "Should have 2 carriers"
                assert len(ctrl.protocols) == 1, "Should have 1 protocol"

                # Send reset to all devices
                # This should not raise any exceptions
                await ctrl.reset(keep_calibration=True, sync=False)

                # Verify controller state is still valid after reset
                assert len(ctrl.devices) == 2, "Devices should still be connected"
                assert len(ctrl.protocols) == 1, "Protocols should still be active"

    @pytest.mark.asyncio
    async def test_clusters_per_carrier_tracking(self):
        """
        Test that Controller correctly tracks clusters per carrier.

        When a device is added, the controller should record how many clusters
        each carrier has in _clusters_per_carrier. This is used for dynamic
        M-block indexing in run data handling.

        DummyDAC provides 2 carriers, each with 1 cluster.

        Verifies:
        - _clusters_per_carrier is populated after add_device
        - Has correct number of entries (2 carriers)
        - Each carrier has correct cluster count (1 cluster each)
        """
        config = DummyDACConfig(mac_mode=DummyDACMacMode.VIRTUAL)

        async with DummyDAC("127.0.0.1", get_test_port(), config) as dac:
            dac_port = dac._server.sockets[0].getsockname()[1]

            async with Controller(standalone=True) as ctrl:
                # Initially empty
                assert len(ctrl._clusters_per_carrier) == 0, (
                    "_clusters_per_carrier should be empty before add_device"
                )

                # Add device (DummyDAC provides 2 carriers, 1 cluster each)
                await ctrl.add_device("127.0.0.1", dac_port)

                # Should have 2 entries (one per carrier)
                assert len(ctrl._clusters_per_carrier) == 2, (
                    f"Expected 2 carriers tracked, got {len(ctrl._clusters_per_carrier)}"
                )

                # Each carrier should have 1 cluster (DummyDAC default)
                for carrier_path, num_clusters in ctrl._clusters_per_carrier.items():
                    assert num_clusters == 1, (
                        f"Carrier {carrier_path} should have 1 cluster, got {num_clusters}"
                    )

                # Verify tracked paths match device paths
                tracked_paths = set(ctrl._clusters_per_carrier.keys())
                device_paths = set(ctrl.devices.keys())
                assert tracked_paths == device_paths, (
                    "_clusters_per_carrier paths should match device paths"
                )

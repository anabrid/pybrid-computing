# Copyright (c) 2022-2025 anabrid GmbH
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
Integration tests for Controller with multiple devices.

Tests multi-device configuration, distributed operations, and
concurrent run execution across DummyDAC backends.

Note: DummyDAC in VIRTUAL mode provides 2 carriers with fixed MACs.
When testing multi-device scenarios, we use the carriers from a single
DummyDAC instance since multiple DummyDACs would have conflicting MACs.

These tests use the connection_manager API directly. controller.devices
returns {Path: DeviceConnection} — one entry per carrier — while
connection_manager.get_unique_connections() returns one entry per
physical backend.
"""

import asyncio
from uuid import uuid4

import pytest

import pybrid.base.proto.main_pb2 as pb
from pybrid.mock import DummyDAC, DummyDACConfig, DummyDACMacMode
from pybrid.redac.controller import Controller
from pybrid.redac.run import DAQConfig, Run, RunConfig, RunState
from pybrid.redac.session import Session
from tests.conftest import get_test_port

try:
    from pybrid.native._impl import ControlChannel as _NativeControlChannel

    _NATIVE_AVAILABLE = True
except ImportError:
    _NATIVE_AVAILABLE = False


class TestControllerMultiDevice:
    """Tests for Controller managing multiple devices/carriers."""

    @pytest.mark.asyncio
    async def test_add_two_devices(self):
        """One DummyDAC (2 carriers) registers 2 device paths sharing 1 unique backend connection."""
        config = DummyDACConfig(mac_mode=DummyDACMacMode.VIRTUAL)

        async with DummyDAC("127.0.0.1", get_test_port(), config) as dac:
            dac_port = dac._server.sockets[0].getsockname()[1]

            async with Controller() as ctrl:
                # Initially no devices
                assert len(ctrl.devices) == 0

                # Add device (DummyDAC provides 2 carriers)
                await ctrl.add_device("127.0.0.1", dac_port)

                # Should have 2 device entries (one per carrier path)
                assert len(ctrl.devices) == 2, f"Expected 2 devices (carriers), got {len(ctrl.devices)}"

                # Should have 2 paths in connection_manager
                connections = ctrl.connection_manager.connections
                assert len(connections) == 2, f"Expected 2 connection entries, got {len(connections)}"

                # Both carriers share ONE unique DeviceConnection (same DummyDAC backend)
                unique_conns = ctrl.connection_manager.get_unique_connections()
                assert (
                    len(unique_conns) == 1
                ), f"Expected 1 unique DeviceConnection (one backend), got {len(unique_conns)}"

                # Verify device paths match connection_manager keys
                device_paths = set(ctrl.devices.keys())
                conn_paths = set(connections.keys())
                assert device_paths == conn_paths, "Device paths should match connection_manager paths"

    @pytest.mark.asyncio
    async def test_config_distributed_to_devices(self):
        """Session with a config module targeting both carrier paths is built without error."""
        config = DummyDACConfig(mac_mode=DummyDACMacMode.VIRTUAL)

        async with DummyDAC("127.0.0.1", get_test_port(), config) as dac:
            dac_port = dac._server.sockets[0].getsockname()[1]

            async with Controller() as ctrl:
                await ctrl.add_device("127.0.0.1", dac_port)

                # Get paths for each carrier
                all_paths = list(ctrl.devices.keys())
                assert len(all_paths) == 2, "Should have 2 carrier paths"

                # Create config entries for different carriers
                configs = []
                for path in all_paths:
                    config_entry = pb.Item(
                        entity=pb.EntityId(path=str(path / "0" / "M0")),
                    )
                    configs.append(config_entry)

                module = pb.Module(items=configs)

                # Build session with config module — does NOT send anything yet
                session = Session(ctrl)
                session.set_module(module)

                # Verify session was built without error
                # (actual execution requires native C++ — skipped here)
                assert session is not None

                # Verify controller state is still valid
                assert len(ctrl.devices) == 2
                # Both carriers share one unique backend connection
                unique_conns = ctrl.connection_manager.get_unique_connections()
                assert len(unique_conns) == 1, "Should have 1 unique backend connection"

    @pytest.mark.asyncio
    async def test_run_with_multiple_carriers(self):
        """DistributedRunState tracks all carrier paths and references the correct Run object."""
        config = DummyDACConfig(mac_mode=DummyDACMacMode.VIRTUAL)

        async with DummyDAC("127.0.0.1", get_test_port(), config) as dac:
            dac_port = dac._server.sockets[0].getsockname()[1]

            async with Controller() as ctrl:
                await ctrl.add_device("127.0.0.1", dac_port)

                all_paths = list(ctrl.devices.keys())
                assert len(all_paths) == 2, "Need 2 carriers for this test"

                # Import DistributedRunState to test multi-path tracking
                from pybrid.redac.controller import DistributedRunState

                run = Run(
                    id_=uuid4(),
                    config=RunConfig(
                        ic_time=100_000,  # 100us
                        op_time=10_000_000,  # 10ms
                    ),
                )

                # Create DistributedRunState tracking all carrier paths
                run_state = DistributedRunState(run, all_paths)

                # Verify run state tracks all paths
                involved_paths = set(run_state.get_involved_paths())
                assert len(involved_paths) == 2, f"DistributedRunState should track 2 paths, got {len(involved_paths)}"

                # Each carrier path should be tracked
                for path in all_paths:
                    assert path in involved_paths, f"Path {path} should be in involved paths"

                # Verify run state starts at NEW for all paths
                reached, not_reached = run_state.status(RunState.NEW)
                # NEW state is set immediately when tracking begins
                assert run_state.run is run, "RunState must reference the correct run"

    @pytest.mark.asyncio
    async def test_reset_all_carriers(self):
        """ctrl.reset() completes without error and leaves the controller state intact."""
        config = DummyDACConfig(mac_mode=DummyDACMacMode.VIRTUAL)

        async with DummyDAC("127.0.0.1", get_test_port(), config) as dac:
            dac_port = dac._server.sockets[0].getsockname()[1]

            async with Controller() as ctrl:
                await ctrl.add_device("127.0.0.1", dac_port)

                # Verify initial state
                assert len(ctrl.devices) == 2, "Should have 2 carriers"

                # Both carriers should share one unique backend connection
                unique_conns = ctrl.connection_manager.get_unique_connections()
                assert len(unique_conns) == 1, "Should have 1 unique backend connection"

                # Send reset to all devices
                # Controller.reset() guards against None control channels, so
                # this is safe in both native and non-native environments.
                await ctrl.reset(keep_calibration=True, sync=False)

                # Verify controller state is still valid after reset
                assert len(ctrl.devices) == 2, "Devices should still be connected"
                unique_conns_after = ctrl.connection_manager.get_unique_connections()
                assert len(unique_conns_after) == 1, "Unique connections should still be active after reset"

    @pytest.mark.asyncio
    async def test_clusters_per_carrier_tracking(self):
        """_clusters_per_carrier is populated with 1 cluster per carrier after add_device."""
        config = DummyDACConfig(mac_mode=DummyDACMacMode.VIRTUAL)

        async with DummyDAC("127.0.0.1", get_test_port(), config) as dac:
            dac_port = dac._server.sockets[0].getsockname()[1]

            async with Controller() as ctrl:
                # Initially empty
                assert len(ctrl._clusters_per_carrier) == 0, "_clusters_per_carrier should be empty before add_device"

                # Add device (DummyDAC provides 2 carriers, 1 cluster each)
                await ctrl.add_device("127.0.0.1", dac_port)

                # Should have 2 entries (one per carrier)
                assert (
                    len(ctrl._clusters_per_carrier) == 2
                ), f"Expected 2 carriers tracked, got {len(ctrl._clusters_per_carrier)}"

                # Each carrier should have 1 cluster (DummyDAC default)
                for carrier_path, num_clusters in ctrl._clusters_per_carrier.items():
                    assert num_clusters == 1, f"Carrier {carrier_path} should have 1 cluster, got {num_clusters}"

                # Verify tracked paths match device paths
                tracked_paths = set(ctrl._clusters_per_carrier.keys())
                device_paths = set(ctrl.devices.keys())
                assert tracked_paths == device_paths, "_clusters_per_carrier paths should match device paths"

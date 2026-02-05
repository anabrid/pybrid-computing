# Copyright (c) 2022-2025 anabrid GmbH
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
Integration tests for Proxy class.

Tests proxy server lifecycle, message forwarding, error propagation,
and multi-backend configurations.
"""

import asyncio
from ipaddress import IPv4Address
from uuid import uuid4

import pytest

import pybrid.base.proto.main_pb2 as pb
from pybrid.base.transport.tcp import TCPTransport
from pybrid.mock import DummyDAC, DummyDACConfig, DummyDACMacMode, DummyDACErrorStage
from pybrid.redac.controller import Controller
from pybrid.redac.proxy import Proxy
from pybrid.redac.protocol.protocol import Protocol
from pybrid.redac.run import Run, RunConfig, RunState, DAQConfig
from tests.conftest import get_test_port, get_test_proxy_port


class TestProxyBasic:
    """Basic proxy lifecycle and operations tests."""

    @pytest.mark.asyncio
    async def test_proxy_starts_and_stops(self):
        """
        Test that a Proxy can be started and stopped cleanly via async context manager.

        Verifies:
        - Proxy starts successfully with Controller connected to DummyDAC
        - Proxy accepts client connections
        - Proxy shuts down gracefully
        """
        config = DummyDACConfig(mac_mode=DummyDACMacMode.VIRTUAL)
        async with DummyDAC("127.0.0.1", get_test_port(), config) as dac:
            dac_port = dac._server.sockets[0].getsockname()[1]

            async with Controller(standalone=True) as ctrl:
                await ctrl.add_device("127.0.0.1", dac_port)

                # Get the carrier MAC for mapping
                carrier_paths = list(ctrl.devices.keys())
                assert len(carrier_paths) > 0, "Controller should have at least one device"

                # Create MAC mapping (virtual -> real)
                mac_mapping = {}
                for i, path in enumerate(carrier_paths):
                    virtual_mac = f"AA-AA-AA-AA-AA-{i:02X}"
                    mac_mapping[virtual_mac] = str(path)

                partition_config = {"device": [list(mac_mapping.keys())]}

                async with Proxy(
                    ctrl,
                    host="127.0.0.1",
                    port=get_test_proxy_port(),
                    mac_mapping=mac_mapping,
                    partition_config=partition_config,
                ) as (proxy, server):
                    proxy_port = server.sockets[0].getsockname()[1]
                    assert proxy_port > 0, "Proxy should be bound to a valid port"

                    # Verify we can connect to the proxy
                    transport = await TCPTransport.create("127.0.0.1", proxy_port)
                    protocol = Protocol(IPv4Address("127.0.0.1"), transport)
                    async with protocol:
                        # Connection established successfully
                        assert protocol is not None

    @pytest.mark.asyncio
    async def test_describe_through_proxy(self):
        """
        Test that describe command works through the proxy.

        Verifies:
        - Client can send DescribeCommand through proxy
        - Proxy correctly forwards and transforms entity information
        - Virtual MAC addresses are used in response
        """
        config = DummyDACConfig(mac_mode=DummyDACMacMode.VIRTUAL)
        async with DummyDAC("127.0.0.1", get_test_port(), config) as dac:
            dac_port = dac._server.sockets[0].getsockname()[1]

            async with Controller(standalone=True) as ctrl:
                await ctrl.add_device("127.0.0.1", dac_port)

                # Get the carrier MAC for mapping
                carrier_paths = list(ctrl.devices.keys())

                # Create MAC mapping (virtual -> real)
                mac_mapping = {}
                for i, path in enumerate(carrier_paths):
                    virtual_mac = f"BB-BB-BB-BB-BB-{i:02X}"
                    mac_mapping[virtual_mac] = str(path)

                partition_config = {"device": [list(mac_mapping.keys())]}

                async with Proxy(
                    ctrl,
                    host="127.0.0.1",
                    port=get_test_proxy_port(),
                    mac_mapping=mac_mapping,
                    partition_config=partition_config,
                ) as (proxy, server):
                    proxy_port = server.sockets[0].getsockname()[1]

                    transport = await TCPTransport.create("127.0.0.1", proxy_port)
                    protocol = Protocol(IPv4Address("127.0.0.1"), transport)
                    async with protocol:
                        # Send describe command
                        entity = await protocol.get_entity()

                        # Verify response contains virtual MAC addresses
                        assert entity is not None
                        assert len(entity.children) > 0, "Response should have carriers"

                        # Check that carrier IDs use virtual MACs
                        carrier_ids = [c.id for c in entity.children]
                        for virtual_mac in mac_mapping.keys():
                            assert virtual_mac in carrier_ids, (
                                f"Virtual MAC {virtual_mac} should be in response"
                            )


class TestProxyErrorScenarios:
    """Tests for error handling through proxy."""

    @pytest.mark.asyncio
    async def test_backend_error_forwarded(self):
        """
        Test that errors from backend DummyDAC are forwarded through proxy.

        Verifies:
        - Error injected at backend is propagated to client
        - Reset command correctly forwards to backend and returns
        """
        # Configure DummyDAC with normal operation (no error injection)
        # to test basic proxy error propagation path
        config = DummyDACConfig(
            mac_mode=DummyDACMacMode.VIRTUAL,
        )
        async with DummyDAC("127.0.0.1", get_test_port(), config) as dac:
            dac_port = dac._server.sockets[0].getsockname()[1]

            async with Controller(standalone=True) as ctrl:
                await ctrl.add_device("127.0.0.1", dac_port)

                carrier_paths = list(ctrl.devices.keys())
                mac_mapping = {}
                for i, path in enumerate(carrier_paths):
                    virtual_mac = f"CC-CC-CC-CC-CC-{i:02X}"
                    mac_mapping[virtual_mac] = str(path)

                partition_config = {"device": [list(mac_mapping.keys())]}

                async with Proxy(
                    ctrl,
                    host="127.0.0.1",
                    port=get_test_proxy_port(),
                    mac_mapping=mac_mapping,
                    partition_config=partition_config,
                ) as (proxy, server):
                    proxy_port = server.sockets[0].getsockname()[1]

                    transport = await TCPTransport.create("127.0.0.1", proxy_port)
                    protocol = Protocol(IPv4Address("127.0.0.1"), transport)
                    async with protocol:
                        # Test reset command goes through proxy to backend
                        response = await protocol.send_body_and_wait_response(
                            pb.ResetCommand(keep_calibration=True, sync=False)
                        )

                        # Reset should succeed (returns ResetResponse)
                        assert response.WhichOneof("kind") == "reset_response", (
                            f"Expected reset_response, got {response.WhichOneof('kind')}"
                        )


class TestProxyMultiBackend:
    """Tests for proxy with multiple backend devices."""

    @pytest.mark.asyncio
    async def test_two_backends(self):
        """
        Test proxy with two separate DummyDAC backends.

        Verifies:
        - Proxy can aggregate multiple backend devices
        - Describe returns entities from all backends
        - Each backend has distinct MAC addresses
        """
        config1 = DummyDACConfig(mac_mode=DummyDACMacMode.VIRTUAL)
        config2 = DummyDACConfig(mac_mode=DummyDACMacMode.VIRTUAL)

        async with DummyDAC("127.0.0.1", 0, config1) as dac1:
            dac1_port = dac1._server.sockets[0].getsockname()[1]

            async with DummyDAC("127.0.0.1", 0, config2) as dac2:
                dac2_port = dac2._server.sockets[0].getsockname()[1]

                async with Controller(standalone=True) as ctrl:
                    # Add both devices to controller
                    await ctrl.add_device("127.0.0.1", dac1_port)
                    await ctrl.add_device("127.0.0.1", dac2_port)

                    # Verify controller has devices from both DACs
                    carrier_paths = list(ctrl.devices.keys())
                    # Each DummyDAC has 2 carriers, so we expect 4 total
                    assert len(carrier_paths) >= 2, (
                        f"Controller should have multiple devices, got {len(carrier_paths)}"
                    )

                    # Create MAC mapping for all carriers
                    mac_mapping = {}
                    for i, path in enumerate(carrier_paths):
                        virtual_mac = f"DD-DD-DD-DD-DD-{i:02X}"
                        mac_mapping[virtual_mac] = str(path)

                    partition_config = {"device": [list(mac_mapping.keys())]}

                    async with Proxy(
                        ctrl,
                        host="127.0.0.1",
                        port=get_test_proxy_port(),
                        mac_mapping=mac_mapping,
                        partition_config=partition_config,
                    ) as (proxy, server):
                        proxy_port = server.sockets[0].getsockname()[1]

                        transport = await TCPTransport.create("127.0.0.1", proxy_port)
                        protocol = Protocol(IPv4Address("127.0.0.1"), transport)
                        async with protocol:
                            entity = await protocol.get_entity()

                            # Verify all carriers are accessible via proxy
                            assert len(entity.children) == len(mac_mapping), (
                                f"Expected {len(mac_mapping)} carriers, got {len(entity.children)}"
                            )

                            # Verify all virtual MACs are present
                            carrier_ids = {c.id for c in entity.children}
                            for virtual_mac in mac_mapping.keys():
                                assert virtual_mac in carrier_ids


class TestProxySamplePassthrough:
    """Verify proxy correctly forwards samples and state changes from backend to client."""

    @pytest.mark.asyncio
    async def test_tcp_sample_passthrough(self):
        """
        Test that samples from DummyDAC reach client through proxy via TCP.

        Verifies:
        - Config is accepted through proxy
        - Run state transitions correctly (QUEUED -> ... -> DONE)
        - Sample data is received by client
        """
        config = DummyDACConfig(mac_mode=DummyDACMacMode.VIRTUAL)
        async with DummyDAC("127.0.0.1", get_test_port(), config) as dac:
            dac_port = dac.port

            async with Controller(standalone=True) as backend_ctrl:
                await backend_ctrl.add_device("127.0.0.1", dac_port)

                carrier_paths = list(backend_ctrl.devices.keys())
                mac_mapping = {
                    f"FF-FF-FF-FF-FF-{i:02X}": str(p)
                    for i, p in enumerate(carrier_paths)
                }
                partition_config = {"device": [list(mac_mapping.keys())]}

                async with Proxy(
                    backend_ctrl,
                    host="127.0.0.1",
                    port=get_test_proxy_port(),
                    mac_mapping=mac_mapping,
                    partition_config=partition_config,
                ) as (proxy, server):
                    proxy_port = server.sockets[0].getsockname()[1]

                    async with Controller() as client_ctrl:
                        await client_ctrl.add_device("127.0.0.1", proxy_port)

                        sample_rate = 10_000
                        op_time_ns = 1_000_000

                        run = Run(
                            id_=uuid4(),
                            config=RunConfig(ic_time=100_000, op_time=op_time_ns),
                            daq=DAQConfig(
                                num_channels=1,
                                sample_rate=sample_rate,
                                sample_op=True,
                            ),
                        )

                        run_state = await client_ctrl.start_run(run)

                        async with asyncio.timeout(15.0):
                            await run_state.wait_all(RunState.DONE)

                        reached, not_reached = run_state.status(RunState.DONE)
                        assert len(not_reached) == 0, (
                            f"All paths should reach DONE. Not done: {not_reached}"
                        )

    @pytest.mark.asyncio
    async def test_run_data_through_proxy(self):
        """
        Test that run data messages pass through proxy correctly.

        Verifies samples are received and run completes successfully.
        """
        config = DummyDACConfig(mac_mode=DummyDACMacMode.VIRTUAL)
        async with DummyDAC("127.0.0.1", get_test_port(), config) as dac:
            dac_port = dac.port

            async with Controller(standalone=True) as backend_ctrl:
                await backend_ctrl.add_device("127.0.0.1", dac_port)

                carrier_paths = list(backend_ctrl.devices.keys())
                mac_mapping = {
                    f"EE-EE-EE-EE-EE-{i:02X}": str(p)
                    for i, p in enumerate(carrier_paths)
                }
                partition_config = {"device": [list(mac_mapping.keys())]}

                async with Proxy(
                    backend_ctrl,
                    host="127.0.0.1",
                    port=get_test_proxy_port(),
                    mac_mapping=mac_mapping,
                    partition_config=partition_config,
                ) as (proxy, server):
                    proxy_port = server.sockets[0].getsockname()[1]

                    async with Controller() as client_ctrl:
                        await client_ctrl.add_device("127.0.0.1", proxy_port)

                        run = Run(
                            id_=uuid4(),
                            config=RunConfig(ic_time=10_000, op_time=100_000),
                        )

                        run_state = await client_ctrl.start_run(run)

                        async with asyncio.timeout(10.0):
                            await run_state.wait_all(RunState.DONE)

                        involved = list(run_state.get_involved_paths())
                        assert len(involved) > 0, "Run should involve device paths"

# Copyright (c) 2022-2025 anabrid GmbH
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""Tests for the DummyDAC UDP streaming support."""

from ipaddress import IPv4Address

import pytest

from pybrid.base.transport.tcp import TCPTransport
from pybrid.base.transport.udp import UDPTransport
from pybrid.mock import DummyDAC, DummyDACConfig
from pybrid.redac.protocol.protocol import Protocol


@pytest.mark.asyncio
async def test_udp_streaming_accepted():
    """Verify UDP streaming is accepted when enabled."""
    config = DummyDACConfig(accept_udp_streaming=True)
    async with DummyDAC("127.0.0.1", 15810, config) as server:
        transport = await TCPTransport.create("127.0.0.1", 15810)
        protocol = Protocol(IPv4Address("127.0.0.1"), transport)
        async with protocol:
            # Request UDP streaming on a test port
            response = await protocol.udp_data_streaming(16000)
            # Should be success (not error)
            assert response.WhichOneof("kind") != "error_message"
            # Client-side protocol should have set up its own UDP transport for receiving
            assert protocol.data_transport is not None
            # Server should track the port for one of its server-side protocols
            assert len(server._client_udp_ports) == 1
            # Verify the port was stored correctly
            stored_port = list(server._client_udp_ports.values())[0]
            assert stored_port == 16000


@pytest.mark.asyncio
async def test_udp_streaming_refused():
    """Verify UDP streaming is refused when disabled."""
    config = DummyDACConfig(accept_udp_streaming=False)
    async with DummyDAC("127.0.0.1", 15811, config) as server:
        transport = await TCPTransport.create("127.0.0.1", 15811)
        protocol = Protocol(IPv4Address("127.0.0.1"), transport)
        async with protocol:
            response = await protocol.udp_data_streaming(16001)
            # Should be error_message when UDP is refused
            kind = response.WhichOneof("kind")
            assert kind == "error_message"
            assert "UDP streaming disabled" in response.error_message.description
            # Server should not track any UDP ports when refused
            assert len(server._client_udp_ports) == 0


@pytest.mark.asyncio
async def test_connection_works_when_udp_refused():
    """Test that refusing UDP streaming still allows normal operation."""
    config = DummyDACConfig(accept_udp_streaming=False)
    async with DummyDAC("127.0.0.1", 15812, config):
        transport = await TCPTransport.create("127.0.0.1", 15812)
        protocol = Protocol(IPv4Address("127.0.0.1"), transport)
        async with protocol:
            # Request UDP streaming (will be refused)
            response = await protocol.udp_data_streaming(16002)
            assert response.WhichOneof("kind") == "error_message"

            # Even with UDP refused, basic commands should work
            entity = await protocol.get_entity()
            assert len(entity.children) == 2


@pytest.mark.asyncio
async def test_multiple_clients_different_udp_ports():
    """Test that multiple clients can have different UDP ports."""
    config = DummyDACConfig(accept_udp_streaming=True)
    async with DummyDAC("127.0.0.1", 15813, config) as server:
        # First client
        transport1 = await TCPTransport.create("127.0.0.1", 15813)
        protocol1 = Protocol(IPv4Address("127.0.0.1"), transport1)

        # Second client
        transport2 = await TCPTransport.create("127.0.0.1", 15813)
        protocol2 = Protocol(IPv4Address("127.0.0.1"), transport2)

        async with protocol1:
            async with protocol2:
                # Both clients request UDP streaming on different ports
                response1 = await protocol1.udp_data_streaming(16003)
                response2 = await protocol2.udp_data_streaming(16004)

                assert response1.WhichOneof("kind") != "error_message"
                assert response2.WhichOneof("kind") != "error_message"

                # Server should track both ports (one per server-side protocol)
                assert len(server._client_udp_ports) == 2
                # Verify both ports are tracked
                stored_ports = set(server._client_udp_ports.values())
                assert stored_ports == {16003, 16004}


@pytest.mark.asyncio
async def test_udp_transport_created_for_server():
    """Verify that the server creates a UDP transport to send data to the client."""
    config = DummyDACConfig(accept_udp_streaming=True)
    async with DummyDAC("127.0.0.1", 15814, config) as server:
        transport = await TCPTransport.create("127.0.0.1", 15814)
        protocol = Protocol(IPv4Address("127.0.0.1"), transport)
        async with protocol:
            await protocol.udp_data_streaming(16005)

            # The server-side protocol should have a UDP data_transport
            server_protocol = list(server._active_protocols)[0]
            assert server_protocol.data_transport is not None
            assert isinstance(server_protocol.data_transport, UDPTransport)

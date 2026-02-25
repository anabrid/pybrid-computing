# Copyright (c) 2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
Unit tests for the ConnectionManager class.

ConnectionManager owns device connections: discovery, topology detection,
channel creation, and lifecycle management. These tests verify:
- Initial empty state
- Single-device discovery and registration (direct mode)
- Multi-device discovery and registration (direct mode)
- Proxy mode detection when a single endpoint reports multiple carriers
- Mixed mode rejection (cannot combine direct + proxy)
- Multiple proxy rejection (cannot connect to two proxy endpoints)
- Connection lookup by path
- Unique connection set derivation
- close_all() cleanup

All tests use mocks — no real network connections are made.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call

import pybrid.base.proto.main_pb2 as pb

from pybrid.redac.connection import ConnectionManager, CarrierInfo
from pybrid.redac.channel import DeviceConnection
from pybrid.redac.control import AsyncControlChannel
from pybrid.redac.entities import Path


def _make_entity_with_carriers(carrier_macs: list[str]) -> pb.Entity:
    """
    Build a pb.Entity tree with the given list of carrier MACs as child entities.

    Each carrier is a child entity whose id is '/<mac>'.
    The root entity id is '/' (as returned by a real device describe call).
    """
    root = pb.Entity()
    root.id = "/"
    for mac in carrier_macs:
        child = root.children.add()
        child.id = f"/{mac}"
        # Mark children as CARRIER type so topology detection can identify them.
        # The exact field name depends on the Entity proto definition; we use
        # class_ = 1 as a stand-in (CARRIER enum value from firmware).
        child.class_ = 1  # CARRIER
    return root


def _make_mock_channel(host: str = "127.0.0.1", port: int = 5732) -> MagicMock:
    """
    Create a mock AsyncControlChannel with describe() returning a stub entity.

    The describe() coroutine returns an entity with a single carrier by default.
    """
    channel = MagicMock(spec=AsyncControlChannel)
    channel.remote_host = host
    channel.remote_port = port
    channel.is_connected = True

    channel.describe = AsyncMock(
        return_value=_make_entity_with_carriers(["AA-BB-CC-DD-EE-01"])
    )
    channel.stop = AsyncMock()
    return channel


@pytest.fixture
def manager() -> ConnectionManager:
    """Provide a fresh ConnectionManager for each test."""
    return ConnectionManager()


@pytest.fixture
def single_carrier_entity() -> pb.Entity:
    """Entity with exactly one carrier (direct mode scenario)."""
    return _make_entity_with_carriers(["AA-BB-CC-DD-EE-01"])


@pytest.fixture
def two_carrier_entity() -> pb.Entity:
    """Entity with two carriers under one host (proxy mode scenario)."""
    return _make_entity_with_carriers(["AA-BB-CC-DD-EE-01", "AA-BB-CC-DD-EE-02"])


class TestConnectionManagerDirectMode:

    @pytest.mark.asyncio
    async def test_add_single_device_direct_mode(
        self, manager: ConnectionManager, single_carrier_entity: pb.Entity
    ):
        mock_channel = _make_mock_channel()
        mock_channel.describe = AsyncMock(return_value=single_carrier_entity)

        mock_connection = MagicMock(spec=DeviceConnection)
        mock_connection.control = mock_channel

        with (
            patch.object(
                ConnectionManager,
                "_discover_device",
                new=AsyncMock(return_value=single_carrier_entity),
            ),
            patch.object(
                ConnectionManager,
                "_create_connections",
                new=AsyncMock(
                    return_value={Path.parse("AA-BB-CC-DD-EE-01"): mock_connection}
                ),
            ),
        ):
            carriers, connections = await manager.add_device("127.0.0.1", 5732)

        assert manager.topology_mode == "direct"
        assert len(manager.connections) == 1
        assert len(carriers) == 1

    @pytest.mark.asyncio
    async def test_add_multiple_devices_direct_mode(
        self, manager: ConnectionManager, single_carrier_entity: pb.Entity
    ):
        mac1 = "AA-BB-CC-DD-EE-01"
        mac2 = "AA-BB-CC-DD-EE-02"
        entity1 = _make_entity_with_carriers([mac1])
        entity2 = _make_entity_with_carriers([mac2])

        conn1 = MagicMock(spec=DeviceConnection)
        conn2 = MagicMock(spec=DeviceConnection)
        path1 = Path.parse(mac1)
        path2 = Path.parse(mac2)

        discover_responses = [entity1, entity2]
        create_responses = [
            {path1: conn1},
            {path2: conn2},
        ]

        async def fake_discover(self_inner, host, port):
            return discover_responses.pop(0)

        async def fake_create(self_inner, host, port, carriers):
            return create_responses.pop(0)

        with (
            patch.object(ConnectionManager, "_discover_device", new=fake_discover),
            patch.object(ConnectionManager, "_create_connections", new=fake_create),
        ):
            await manager.add_device("127.0.0.1", 5732)
            await manager.add_device("127.0.0.2", 5732)

        assert manager.topology_mode == "direct"
        assert len(manager.connections) == 2
        # The two connections must be distinct objects
        conns = list(manager.connections.values())
        assert conns[0] is not conns[1]


class TestConnectionManagerProxyMode:

    @pytest.mark.asyncio
    async def test_proxy_mode_detection(
        self, manager: ConnectionManager, two_carrier_entity: pb.Entity
    ):
        """When a single endpoint reports multiple carriers, all paths share one DeviceConnection."""
        mac1 = "AA-BB-CC-DD-EE-01"
        mac2 = "AA-BB-CC-DD-EE-02"
        shared_conn = MagicMock(spec=DeviceConnection)
        path1 = Path.parse(mac1)
        path2 = Path.parse(mac2)

        async def fake_discover(self_inner, host, port):
            return two_carrier_entity

        # Both paths map to the same shared_conn (proxy: one connection for all)
        async def fake_create(self_inner, host, port, carriers):
            return {path1: shared_conn, path2: shared_conn}

        with (
            patch.object(ConnectionManager, "_discover_device", new=fake_discover),
            patch.object(ConnectionManager, "_create_connections", new=fake_create),
        ):
            carriers, connections = await manager.add_device("127.0.0.1", 5732)

        assert manager.topology_mode == "proxy"
        assert len(manager.connections) == 2
        # Both paths point to the same object
        vals = list(manager.connections.values())
        assert vals[0] is vals[1]

    @pytest.mark.asyncio
    async def test_mixed_mode_rejection(
        self,
        manager: ConnectionManager,
        single_carrier_entity: pb.Entity,
        two_carrier_entity: pb.Entity,
    ):
        """Adding a proxy-style endpoint after a direct connection is established raises an error."""
        mac_direct = "AA-BB-CC-DD-EE-01"
        mac_p1 = "BB-BB-CC-DD-EE-01"
        mac_p2 = "BB-BB-CC-DD-EE-02"

        conn_direct = MagicMock(spec=DeviceConnection)
        conn_proxy = MagicMock(spec=DeviceConnection)
        path_direct = Path.parse(mac_direct)
        path_p1 = Path.parse(mac_p1)
        path_p2 = Path.parse(mac_p2)

        discover_responses = [single_carrier_entity, two_carrier_entity]
        create_responses = [
            {path_direct: conn_direct},
            {path_p1: conn_proxy, path_p2: conn_proxy},
        ]

        async def fake_discover(self_inner, host, port):
            return discover_responses.pop(0)

        async def fake_create(self_inner, host, port, carriers):
            return create_responses.pop(0)

        with (
            patch.object(ConnectionManager, "_discover_device", new=fake_discover),
            patch.object(ConnectionManager, "_create_connections", new=fake_create),
        ):
            # First add_device: direct mode established
            await manager.add_device("127.0.0.1", 5732)
            assert manager.topology_mode == "direct"

            # Second add_device: should raise because topology would change to proxy
            with pytest.raises(Exception, match="[Mm]ix|[Tt]opology|[Pp]roxy|[Cc]ombine"):
                await manager.add_device("127.0.0.2", 5732)

    @pytest.mark.asyncio
    async def test_multiple_proxy_rejection(
        self, manager: ConnectionManager, two_carrier_entity: pb.Entity
    ):
        """Connecting to a second proxy endpoint after a proxy is established raises an error."""
        mac_p1 = "AA-BB-CC-DD-EE-01"
        mac_p2 = "AA-BB-CC-DD-EE-02"
        mac_p3 = "CC-BB-CC-DD-EE-01"
        mac_p4 = "CC-BB-CC-DD-EE-02"

        conn_proxy1 = MagicMock(spec=DeviceConnection)
        conn_proxy2 = MagicMock(spec=DeviceConnection)
        entity2 = _make_entity_with_carriers([mac_p3, mac_p4])

        path_p1 = Path.parse(mac_p1)
        path_p2 = Path.parse(mac_p2)
        path_p3 = Path.parse(mac_p3)
        path_p4 = Path.parse(mac_p4)

        discover_responses = [two_carrier_entity, entity2]
        create_responses = [
            {path_p1: conn_proxy1, path_p2: conn_proxy1},
            {path_p3: conn_proxy2, path_p4: conn_proxy2},
        ]

        async def fake_discover(self_inner, host, port):
            return discover_responses.pop(0)

        async def fake_create(self_inner, host, port, carriers):
            return create_responses.pop(0)

        with (
            patch.object(ConnectionManager, "_discover_device", new=fake_discover),
            patch.object(ConnectionManager, "_create_connections", new=fake_create),
        ):
            # First add_device: proxy mode established
            await manager.add_device("127.0.0.1", 5732)
            assert manager.topology_mode == "proxy"

            # Second add_device to another proxy: must be rejected
            with pytest.raises(Exception, match="[Mm]ultiple|[Pp]roxy|[Ss]econd|[Cc]annot"):
                await manager.add_device("127.0.0.2", 5732)


class TestConnectionManagerLookup:

    @pytest.fixture
    async def manager_with_two_direct_devices(self) -> ConnectionManager:
        """Return a ConnectionManager pre-populated with two direct-mode connections."""
        manager = ConnectionManager()
        mac1 = "AA-BB-CC-DD-EE-01"
        mac2 = "AA-BB-CC-DD-EE-02"
        entity1 = _make_entity_with_carriers([mac1])
        entity2 = _make_entity_with_carriers([mac2])

        conn1 = MagicMock(spec=DeviceConnection)
        conn2 = MagicMock(spec=DeviceConnection)
        path1 = Path.parse(mac1)
        path2 = Path.parse(mac2)

        discover_responses = [entity1, entity2]
        create_responses = [{path1: conn1}, {path2: conn2}]

        async def fake_discover(self_inner, host, port):
            return discover_responses.pop(0)

        async def fake_create(self_inner, host, port, carriers):
            return create_responses.pop(0)

        with (
            patch.object(ConnectionManager, "_discover_device", new=fake_discover),
            patch.object(ConnectionManager, "_create_connections", new=fake_create),
        ):
            await manager.add_device("127.0.0.1", 5732)
            await manager.add_device("127.0.0.2", 5732)

        return manager

    @pytest.fixture
    async def manager_with_proxy(self) -> ConnectionManager:
        """Return a ConnectionManager in proxy mode with two carriers sharing one connection."""
        manager = ConnectionManager()
        mac1 = "AA-BB-CC-DD-EE-01"
        mac2 = "AA-BB-CC-DD-EE-02"
        entity = _make_entity_with_carriers([mac1, mac2])

        shared_conn = MagicMock(spec=DeviceConnection)
        path1 = Path.parse(mac1)
        path2 = Path.parse(mac2)

        async def fake_discover(self_inner, host, port):
            return entity

        async def fake_create(self_inner, host, port, carriers):
            return {path1: shared_conn, path2: shared_conn}

        with (
            patch.object(ConnectionManager, "_discover_device", new=fake_discover),
            patch.object(ConnectionManager, "_create_connections", new=fake_create),
        ):
            await manager.add_device("127.0.0.1", 5732)

        return manager

    @pytest.mark.asyncio
    async def test_get_connection_missing(
        self, manager_with_two_direct_devices: ConnectionManager
    ):
        """get_connection() raises KeyError for an unknown path."""
        manager = manager_with_two_direct_devices
        unknown_path = Path.parse("FF-FF-FF-FF-FF-FF")
        with pytest.raises(KeyError):
            manager.get_connection(unknown_path)

    @pytest.mark.asyncio
    async def test_get_unique_connections_direct(
        self, manager_with_two_direct_devices: ConnectionManager
    ):
        """In direct mode with N devices, get_unique_connections() returns N distinct objects."""
        manager = manager_with_two_direct_devices
        unique = manager.get_unique_connections()
        assert len(unique) == 2

    @pytest.mark.asyncio
    async def test_get_unique_connections_proxy(
        self, manager_with_proxy: ConnectionManager
    ):
        """In proxy mode, get_unique_connections() returns 1 object even though multiple paths exist."""
        manager = manager_with_proxy
        # Two paths, but same object
        assert len(manager.connections) == 2
        unique = manager.get_unique_connections()
        assert len(unique) == 1


class TestConnectionManagerCloseAll:

    @pytest.mark.asyncio
    async def test_close_all(self, manager: ConnectionManager):
        """close_all() stops all unique channels and leaves connections empty."""
        mac1 = "AA-BB-CC-DD-EE-01"
        mac2 = "AA-BB-CC-DD-EE-02"
        entity1 = _make_entity_with_carriers([mac1])
        entity2 = _make_entity_with_carriers([mac2])

        conn1 = MagicMock(spec=DeviceConnection)
        conn1.control = MagicMock(spec=AsyncControlChannel)
        conn1.control.stop = AsyncMock()
        conn2 = MagicMock(spec=DeviceConnection)
        conn2.control = MagicMock(spec=AsyncControlChannel)
        conn2.control.stop = AsyncMock()

        path1 = Path.parse(mac1)
        path2 = Path.parse(mac2)

        discover_responses = [entity1, entity2]
        create_responses = [{path1: conn1}, {path2: conn2}]

        async def fake_discover(self_inner, host, port):
            return discover_responses.pop(0)

        async def fake_create(self_inner, host, port, carriers):
            return create_responses.pop(0)

        with (
            patch.object(ConnectionManager, "_discover_device", new=fake_discover),
            patch.object(ConnectionManager, "_create_connections", new=fake_create),
        ):
            await manager.add_device("127.0.0.1", 5732)
            await manager.add_device("127.0.0.2", 5732)

        assert len(manager.connections) == 2

        await manager.close_all()

        assert manager.connections == {}

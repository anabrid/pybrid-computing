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
from unittest.mock import AsyncMock, MagicMock, patch

import pybrid.base.proto.main_pb2 as pb

from pybrid.redac.connection import ConnectionManager
from pybrid.redac.channel import DeviceConnection
from pybrid.redac.control import AsyncControlChannel
from pybrid.redac.entities import Path


def _make_entity_with_carriers(carrier_macs: list[str]) -> pb.Entity:
    """Build a pb.Entity tree with the given carrier MACs as child entities."""
    root = pb.Entity()
    root.id = "/"
    for mac in carrier_macs:
        child = root.children.add()
        child.id = f"/{mac}"
        child.class_ = 1  # CARRIER
    return root


def _wrap_entity_as_module(entity: pb.Entity) -> pb.Module:
    """Wrap a pb.Entity in a pb.Module with an EntitySpecification item,
    matching the format returned by _discover_device."""
    item = pb.Item(
        entity_specification=pb.EntitySpecification(entity=entity)
    )
    return pb.Module(items=[item])


def _make_discover_module(carrier_macs: list[str]) -> pb.Module:
    """Build an entity tree and wrap it as a Module for discover mocks."""
    return _wrap_entity_as_module(_make_entity_with_carriers(carrier_macs))


@pytest.fixture
def manager() -> ConnectionManager:
    """Provide a fresh ConnectionManager for each test."""
    return ConnectionManager()


@pytest.fixture
def single_carrier_module() -> pb.Module:
    """Module with exactly one carrier (direct mode scenario)."""
    return _make_discover_module(["AA-BB-CC-DD-EE-01"])


@pytest.fixture
def two_carrier_module() -> pb.Module:
    """Module with two carriers under one host (proxy mode scenario)."""
    return _make_discover_module(["AA-BB-CC-DD-EE-01", "AA-BB-CC-DD-EE-02"])


class TestConnectionManagerDirectMode:

    @pytest.mark.asyncio
    async def test_add_single_device_direct_mode(
        self, manager: ConnectionManager, single_carrier_module: pb.Module
    ):
        mock_connection = MagicMock(spec=DeviceConnection)

        with (
            patch.object(
                ConnectionManager,
                "_discover_device",
                new=AsyncMock(return_value=single_carrier_module),
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
        self, manager: ConnectionManager
    ):
        mac1 = "AA-BB-CC-DD-EE-01"
        mac2 = "AA-BB-CC-DD-EE-02"
        module1 = _make_discover_module([mac1])
        module2 = _make_discover_module([mac2])

        conn1 = MagicMock(spec=DeviceConnection)
        conn2 = MagicMock(spec=DeviceConnection)
        path1 = Path.parse(mac1)
        path2 = Path.parse(mac2)

        discover_responses = [module1, module2]
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
        conns = list(manager.connections.values())
        assert conns[0] is not conns[1]


class TestConnectionManagerProxyMode:

    @pytest.mark.asyncio
    async def test_proxy_mode_detection(
        self, manager: ConnectionManager, two_carrier_module: pb.Module
    ):
        """When a single endpoint reports multiple carriers, all paths share one DeviceConnection."""
        mac1 = "AA-BB-CC-DD-EE-01"
        mac2 = "AA-BB-CC-DD-EE-02"
        shared_conn = MagicMock(spec=DeviceConnection)
        path1 = Path.parse(mac1)
        path2 = Path.parse(mac2)

        async def fake_discover(self_inner, host, port):
            return two_carrier_module

        async def fake_create(self_inner, host, port, carriers):
            return {path1: shared_conn, path2: shared_conn}

        with (
            patch.object(ConnectionManager, "_discover_device", new=fake_discover),
            patch.object(ConnectionManager, "_create_connections", new=fake_create),
        ):
            carriers, connections = await manager.add_device("127.0.0.1", 5732)

        assert manager.topology_mode == "proxy"
        assert len(manager.connections) == 2
        vals = list(manager.connections.values())
        assert vals[0] is vals[1]

    @pytest.mark.asyncio
    async def test_mixed_mode_rejection(
        self,
        manager: ConnectionManager,
        single_carrier_module: pb.Module,
        two_carrier_module: pb.Module,
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

        discover_responses = [single_carrier_module, two_carrier_module]
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
            await manager.add_device("127.0.0.1", 5732)
            assert manager.topology_mode == "direct"

            with pytest.raises(Exception, match="[Mm]ix|[Tt]opology|[Pp]roxy|[Cc]ombine"):
                await manager.add_device("127.0.0.2", 5732)

    @pytest.mark.asyncio
    async def test_multiple_proxy_rejection(
        self, manager: ConnectionManager, two_carrier_module: pb.Module
    ):
        """Connecting to a second proxy endpoint after a proxy is established raises an error."""
        mac_p1 = "AA-BB-CC-DD-EE-01"
        mac_p2 = "AA-BB-CC-DD-EE-02"
        mac_p3 = "CC-BB-CC-DD-EE-01"
        mac_p4 = "CC-BB-CC-DD-EE-02"

        conn_proxy1 = MagicMock(spec=DeviceConnection)
        conn_proxy2 = MagicMock(spec=DeviceConnection)
        module2 = _make_discover_module([mac_p3, mac_p4])

        path_p1 = Path.parse(mac_p1)
        path_p2 = Path.parse(mac_p2)
        path_p3 = Path.parse(mac_p3)
        path_p4 = Path.parse(mac_p4)

        discover_responses = [two_carrier_module, module2]
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
            await manager.add_device("127.0.0.1", 5732)
            assert manager.topology_mode == "proxy"

            with pytest.raises(Exception, match="[Mm]ultiple|[Pp]roxy|[Ss]econd|[Cc]annot"):
                await manager.add_device("127.0.0.2", 5732)


class TestConnectionManagerLookup:

    @pytest.fixture
    async def manager_with_two_direct_devices(self) -> ConnectionManager:
        """Return a ConnectionManager pre-populated with two direct-mode connections."""
        manager = ConnectionManager()
        mac1 = "AA-BB-CC-DD-EE-01"
        mac2 = "AA-BB-CC-DD-EE-02"
        module1 = _make_discover_module([mac1])
        module2 = _make_discover_module([mac2])

        conn1 = MagicMock(spec=DeviceConnection)
        conn2 = MagicMock(spec=DeviceConnection)
        path1 = Path.parse(mac1)
        path2 = Path.parse(mac2)

        discover_responses = [module1, module2]
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
        module = _make_discover_module([mac1, mac2])

        shared_conn = MagicMock(spec=DeviceConnection)
        path1 = Path.parse(mac1)
        path2 = Path.parse(mac2)

        async def fake_discover(self_inner, host, port):
            return module

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
        assert len(manager.connections) == 2
        unique = manager.get_unique_connections()
        assert len(unique) == 1


class TestConnectionManagerCloseAll:

    @pytest.mark.asyncio
    async def test_close_all(self, manager: ConnectionManager):
        """close_all() stops all unique channels and leaves connections empty."""
        mac1 = "AA-BB-CC-DD-EE-01"
        mac2 = "AA-BB-CC-DD-EE-02"
        module1 = _make_discover_module([mac1])
        module2 = _make_discover_module([mac2])

        conn1 = MagicMock(spec=DeviceConnection)
        conn1.control = MagicMock(spec=AsyncControlChannel)
        conn1.control.stop = AsyncMock()
        conn2 = MagicMock(spec=DeviceConnection)
        conn2.control = MagicMock(spec=AsyncControlChannel)
        conn2.control.stop = AsyncMock()

        path1 = Path.parse(mac1)
        path2 = Path.parse(mac2)

        discover_responses = [module1, module2]
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

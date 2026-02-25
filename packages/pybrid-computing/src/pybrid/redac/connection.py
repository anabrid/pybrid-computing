# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""Connection lifecycle management for REDAC devices.

This module provides :class:`ConnectionManager`, which owns the full lifecycle
of device connections: discovery via a temporary control channel, topology
detection (direct vs. proxy mode), persistent channel creation, and teardown.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal, List

import pybrid.base.proto.main_pb2 as pb

from pybrid.redac.channel import DeviceConnection

# Avoids a circular import:
# pybrid.redac.entities → pybrid.base.hybrid → base.hybrid.controller
# → pybrid.redac.connection.  The base Path is fully compatible for use as
# dict keys and annotations here.
from pybrid.base.hybrid.entities import Path

logger = logging.getLogger(__name__)


@dataclass
class CarrierInfo:
    """Metadata for a single carrier board discovered during device enumeration."""

    path: Path
    mac: str
    entity: pb.Entity


class ConnectionManager:
    """Owns device connections: discovery, topology detection, channel creation,
    and lifecycle management.

    Connection map: a single ``connections`` dict maps every carrier :class:`Path`
    to its :class:`~pybrid.redac.channel.DeviceConnection`.  In **proxy mode**,
    multiple paths reference the *same* ``DeviceConnection`` object in memory;
    :meth:`get_unique_connections` collapses duplicates via ``set()``.

    Topology rules enforced on every :meth:`add_device` call:
    - Direct and proxy connections cannot be mixed.
    - At most one proxy endpoint may be registered.
    - In proxy mode all carriers behind that endpoint share one DeviceConnection.

    Attributes:
        connections: Mapping from carrier :class:`Path` to
            :class:`~pybrid.redac.channel.DeviceConnection`.  Multiple keys
            may reference the same value object in proxy mode.
        cache_descriptions: Cached entity descriptions from connected devices.
        _topology_mode: ``"direct"`` or ``"proxy"`` once the first device has
            been added; ``None`` until then.
    """

    connections: dict[Path, DeviceConnection]
    cache_descriptions: pb.DescribeBundle
    _topology_mode: Literal["direct", "proxy"] | None

    def __init__(self) -> None:
        self.connections: dict[Path, DeviceConnection] = {}
        self.cache_descriptions: pb.DescribeBundle = pb.DescribeBundle(entities=[])
        self._topology_mode: Literal["direct", "proxy"] | None = None

    @property
    def topology_mode(self) -> Literal["direct", "proxy"] | None:
        """``"direct"``, ``"proxy"``, or ``None`` before any device has been added."""
        return self._topology_mode

    async def add_device(
        self,
        host: str,
        port: int,
    ) -> tuple[list[CarrierInfo], dict[Path, DeviceConnection]]:
        """Discover, classify, connect, and register one endpoint.

        Opens a temporary control channel to discover the device topology,
        then creates persistent connections and merges them into :attr:`connections`.

        :raises RuntimeError: If mixing direct and proxy connections, if a second
            proxy endpoint is added, or if the describe call times out.
        """
        entity = await self._discover_device(host, port)

        entities = entity
        if entities.id == "/":
            for child in entities.children:
                self.cache_descriptions.entities.append(child)
        else:
            self.cache_descriptions.entities.append(entity)
        carriers = self._detect_topology(entity)
        new_connections = await self._create_connections(host, port, carriers)
        self._register(carriers, new_connections)
        return carriers, new_connections

    def get_connection(self, path: Path) -> DeviceConnection:
        """:raises KeyError: If *path* is not registered."""
        return self.connections[path]

    def get_unique_connections(self) -> set[DeviceConnection]:
        """Collapse duplicate connections (proxy mode) by identity."""
        return set(self.connections.values())

    async def close_all(self) -> None:
        """Stop all unique channels and clear :attr:`connections`."""
        unique = self.get_unique_connections()
        errors: list[Exception] = []
        try:
            for conn in unique:
                try:
                    # Stop data channel first — it may depend on the control
                    # channel's TCP transport for TCP fallback streaming.
                    if hasattr(conn, "data") and conn.data is not None:
                        conn.data.stop()
                    if hasattr(conn, "control") and conn.control is not None:
                        await conn.control.stop()
                    elif hasattr(conn, "stop"):
                        await conn.stop()
                except Exception as exc:
                    logger.error("Error while stopping connection %r: %s", conn, exc)
                    errors.append(exc)
        finally:
            self.connections.clear()
            self._topology_mode = None

        if errors:
            raise RuntimeError(
                f"close_all() encountered {len(errors)} error(s) while stopping "
                f"channels: {errors}"
            )

    async def _discover_device(self, host: str, port: int) -> pb.Entity:
        """Open a temporary control channel, describe the device, and close."""
        from pybrid.redac.control import AsyncControlChannel

        channel = await AsyncControlChannel.create(host, port)
        try:
            channel.start()
            entity = await channel.describe()
        finally:
            await channel.stop()
        return entity

    def _detect_topology(self, entity: pb.Entity) -> list[CarrierInfo]:
        """Parse the entity tree and return one :class:`CarrierInfo` per carrier.

        - 1 carrier → direct mode.
        - N > 1 carriers → proxy mode.

        :raises ValueError: If no carriers are found.
        """
        carriers: list[CarrierInfo] = []

        if entity.class_ == pb.Entity.CARRIER:
            # Root entity is itself a carrier (direct single-device mode).
            mac = entity.id.strip("/")
            carriers.append(CarrierInfo(
                path=Path.parse(mac),
                mac=mac,
                entity=entity,
            ))
        else:
            # Root is a DEVICE or container — carriers are children.
            for child in entity.children:
                if child.class_ == pb.Entity.CARRIER:
                    mac = child.id.strip("/")
                    carriers.append(CarrierInfo(
                        path=Path.parse(mac),
                        mac=mac,
                        entity=child,
                    ))

        if not carriers:
            raise ValueError(
                f"No carrier entities found in the entity tree rooted at '{entity.id}'. "
                "The device may not have reported any carriers."
            )

        logger.debug(
            "_detect_topology: found %d carrier(s): %s",
            len(carriers),
            [c.mac for c in carriers],
        )
        return carriers

    async def _create_connections(
        self,
        host: str,
        port: int,
        carriers: list[CarrierInfo],
    ) -> dict[Path, DeviceConnection]:
        """Create persistent control and data channels for all carriers.

        Direct mode (1 carrier): one DeviceConnection per carrier.
        Proxy mode (N > 1 carriers): one shared DeviceConnection for all carriers.
        """
        from pybrid.redac.control import AsyncControlChannel
        from pybrid.native import SampleDecodingDataChannel, SampleLockFreeBuffer

        control = await AsyncControlChannel.create(host, port)
        control.start()

        # The DataChannel shares the ControlChannel's TCP transport and routes
        # control responses back via on_tcp_response().  The ControlChannel's
        # recv thread must be stopped before the DataChannel starts so it can
        # take exclusive ownership of the transport.
        output_queue = SampleLockFreeBuffer()
        data_channel = SampleDecodingDataChannel()
        data_channel.set_output_queue(output_queue)
        data_channel.set_tcp_transport(control.transport)
        data_channel.set_control_response_callback(
            lambda data: control.native.on_tcp_response(data)
        )

        control.native.stop_recv_thread()
        data_channel.start()

        conn = DeviceConnection(control=control, data=data_channel, output_queue=output_queue)

        new_connections: dict[Path, DeviceConnection] = {}
        if len(carriers) == 1:
            new_connections[carriers[0].path] = conn
            logger.debug(
                "_create_connections: direct mode, carrier=%s, host=%s:%d",
                carriers[0].mac,
                host,
                port,
            )
        else:
            for carrier in carriers:
                new_connections[carrier.path] = conn
            logger.debug(
                "_create_connections: proxy mode, %d carriers sharing one connection, host=%s:%d",
                len(carriers),
                host,
                port,
            )

        return new_connections

    def _register(
        self,
        carriers: list[CarrierInfo],
        new_connections: dict[Path, DeviceConnection],
    ) -> None:
        """Merge *new_connections* into :attr:`connections` and validate topology.

        :raises RuntimeError: On topology inconsistency (mixing modes or multiple proxies).
        """
        incoming_topology: Literal["direct", "proxy"] = (
            "proxy" if len(carriers) > 1 else "direct"
        )

        if self._topology_mode is not None:
            if self._topology_mode != incoming_topology:
                raise RuntimeError(
                    f"Cannot mix direct and proxy connections: existing topology is "
                    f"'{self._topology_mode}' but incoming connections suggest "
                    f"'{incoming_topology}'. Mix of topologies is not supported."
                )
            if self._topology_mode == "proxy":
                # Only one proxy endpoint is allowed; a new unique DeviceConnection
                # would mean a second proxy.
                existing_unique = set(self.connections.values())
                incoming_unique = set(new_connections.values())
                if not incoming_unique.issubset(existing_unique):
                    raise RuntimeError(
                        "Cannot connect to multiple proxies: a proxy connection is "
                        "already registered and adding a second proxy endpoint is not "
                        "supported."
                    )
        else:
            self._topology_mode = incoming_topology

        self.connections.update(new_connections)
        logger.debug(
            "_register: topology=%s, total connections=%d",
            self._topology_mode,
            len(self.connections),
        )

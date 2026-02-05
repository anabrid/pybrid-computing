# Copyright (c) 2022-2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""DummyDAC mock server for testing pybrid client code."""

import asyncio
import logging
from asyncio import StreamReader, StreamWriter, Server
from ipaddress import IPv4Address
import pybrid.base.proto.main_pb2 as pb
from pybrid.base.transport import PassthroughTransport
from pybrid.redac.protocol.protocol import Protocol
from pybrid.mock.config import DummyDACConfig, DummyDACMacMode

logger = logging.getLogger(__name__)


class DummyDAC:
    """
    A mock DAC server that simulates a real LUCIDAC device for testing.

    This class implements an async TCP server that accepts client connections
    and manages protocol lifecycle. It follows the same patterns as the
    Proxy class for consistency.

    Usage:
        async with DummyDAC("127.0.0.1", 5732, config) as server:
            # Server is running and accepting connections
            ...
        # Server is stopped and cleaned up

    :param host: The host address to bind to.
    :param port: The port number to listen on.
    :param config: Configuration for the mock DAC behavior.
    """

    host: str
    _port: int
    config: DummyDACConfig
    _server: Server | None
    _active_protocols: set[Protocol]
    _carrier_macs: list[str]
    _client_udp_ports: dict[Protocol, int]

    def __init__(self, host: str, port: int, config: DummyDACConfig):
        """
        Initialize the DummyDAC server.

        :param host: The host address to bind to (e.g., "127.0.0.1").
        :param port: The port number to listen on.
        :param config: Configuration for the mock DAC behavior.
        """
        self.host = host
        self._port = port
        self.config = config
        self._server = None
        self._active_protocols = set()
        self._carrier_macs = self._generate_carrier_macs()
        self._stored_config: pb.ConfigBundle | None = None
        self._client_udp_ports = {}
        self._handlers = self._create_handlers()

    @property
    def port(self) -> int:
        """Get the port the server is listening on."""
        if self._server is not None and self._server.sockets:
            return self._server.sockets[0].getsockname()[1]
        return self._port

    def _create_handlers(self) -> dict:
        """
        Create handler instances for each command type.

        :return: Dictionary mapping field numbers to handler instances.
        """
        from pybrid.mock.handler import (
            DescribeHandler,
            ResetHandler,
            ConfigHandler,
            ExtractHandler,
            UDPStreamingHandler,
            StartRunHandler,
            RegisterExternalEntitiesHandler,
        )

        return {
            pb.MessageV1.DESCRIBE_COMMAND_FIELD_NUMBER: DescribeHandler(self),
            pb.MessageV1.RESET_COMMAND_FIELD_NUMBER: ResetHandler(self),
            pb.MessageV1.CONFIG_COMMAND_FIELD_NUMBER: ConfigHandler(self),
            pb.MessageV1.EXTRACT_COMMAND_FIELD_NUMBER: ExtractHandler(self),
            pb.MessageV1.UDP_DATA_STREAMING_COMMAND_FIELD_NUMBER: UDPStreamingHandler(self),
            pb.MessageV1.START_RUN_COMMAND_FIELD_NUMBER: StartRunHandler(self),
            pb.MessageV1.REGISTER_EXTERNAL_ENTITIES_COMMAND_FIELD_NUMBER: RegisterExternalEntitiesHandler(self),
        }

    def _generate_carrier_macs(self) -> list[str]:
        """
        Generate MAC addresses for the virtual carriers.

        In VIRTUAL mode, returns fixed MAC addresses for deterministic testing.
        In PHYSICAL mode, returns fixed but realistic-looking MAC addresses.

        :return: List of two MAC addresses in XX-XX-XX-XX-XX-XX format.
        """
        if self.config.mac_mode == DummyDACMacMode.VIRTUAL:
            return ["00-00-00-00-00-00", "00-00-00-00-00-01"]
        else:
            # Fixed MAC addresses for deterministic behavior
            return ["AB-CD-EF-12-34-56", "AB-CD-EF-12-34-57"]

    def _dict_to_pb_entity(self, id_: str, data: dict) -> pb.Entity:
        """
        Convert a dictionary representation to a protobuf Entity.

        :param id_: The entity ID string.
        :param data: Dictionary containing entity attributes and children.
        :return: A protobuf Entity instance.
        """
        version = pb.Version(
            major=data["version"][0],
            minor=data["version"][1],
            patch=data["version"][2]
        )

        entity = pb.Entity(
            id=id_.lstrip('/'),
            class_=data["class"],
            type=data["type"],
            variant=data["variant"],
            version=version,
            eui=data["eui"]
        )

        # Recursively add children
        for key, value in data.items():
            if key.startswith('/'):
                child_entity = self._dict_to_pb_entity(key, value)
                entity.children.append(child_entity)

        return entity

    def _build_entity_tree(self) -> pb.Entity:
        """
        Build the entity tree for the DummyDAC.

        Creates a root entity containing carrier entities for each MAC address
        in self._carrier_macs. Each carrier has a cluster with M0, M1, U, C, I, SH
        blocks, plus T and CTRL entities. FP is intentionally excluded.

        :return: A protobuf Entity representing the root with all carriers.
        """
        root = pb.Entity(id="", class_=pb.Entity.DEVICE)

        for mac in self._carrier_macs:
            carrier_dict = {
                "class": 1,  # CARRIER
                "type": 1,
                "variant": 1,
                "version": [1, 0, 0],
                "eui": "00-00-00-00-00-00-00-00",
                "/0": {
                    "class": 2,  # CLUSTER
                    "type": 1,
                    "variant": 1,
                    "version": [1, 0, 0],
                    "eui": "00-00-00-00-00-00-00-00",
                    "/M0": {
                        "class": 3,
                        "type": 1,
                        "variant": 1,
                        "version": [1, 0, 0],
                        "eui": "00-04-A3-0B-00-16-92-1B",
                    },
                    "/M1": {
                        "class": 3,
                        "type": 2,
                        "variant": 1,
                        "version": [1, 0, 0],
                        "eui": "00-04-A3-0B-00-16-7D-6D",
                    },
                    "/U": {
                        "class": 4,
                        "type": 1,
                        "variant": 1,
                        "version": [1, 0, 0],
                        "eui": "00-04-A3-0B-00-15-76-7A",
                    },
                    "/C": {
                        "class": 5,
                        "type": 1,
                        "variant": 1,
                        "version": [1, 0, 0],
                        "eui": "FF-FF-D8-47-8F-3F-8E-F5",
                    },
                    "/I": {
                        "class": 6,
                        "type": 1,
                        "variant": 1,
                        "version": [1, 0, 0],
                        "eui": "00-04-A3-0B-00-15-3D-F5",
                    },
                    "/SH": {
                        "class": 7,
                        "type": 1,
                        "variant": 1,
                        "version": [1, 0, 0],
                        "eui": "00-04-A3-0B-00-16-94-9F",
                    },
                },
                "/T": {
                    "class": 10,
                    "type": 1,
                    "variant": 1,
                    "version": [1, 0, 0],
                    "eui": "00-04-A3-0B-00-16-7E-10",
                },
                "/CTRL": {
                    "class": 9,
                    "type": 1,
                    "variant": 1,
                    "version": [1, 0, 0],
                    "eui": "00-04-A3-0B-00-16-7E-05",
                },
                # FP is intentionally excluded
            }
            carrier_entity = self._dict_to_pb_entity(f"/{mac}", carrier_dict)
            root.children.append(carrier_entity)

        return root

    async def __aenter__(self) -> "DummyDAC":
        """
        Start the server and begin accepting connections.

        Creates an asyncio TCP server and enters its context manager.
        The server will start listening for incoming connections.

        :return: The DummyDAC instance itself (not a tuple).
        """
        self._server = await asyncio.start_server(
            self._client_connected, self.host, self.port
        )
        await self._server.__aenter__()
        logger.info(
            "DummyDAC server started on %s:%d with MACs %s",
            self.host,
            self.port,
            self._carrier_macs,
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """
        Stop the server and clean up all active connections.

        Performs graceful shutdown by:
        1. Stopping the TCP server (no new connections accepted)
        2. Stopping all active protocol instances
        3. Clearing the active protocols set

        :param exc_type: Exception type if an exception was raised.
        :param exc_val: Exception value if an exception was raised.
        :param exc_tb: Exception traceback if an exception was raised.
        """
        logger.info("DummyDAC server shutting down...")

        # Stop all active protocols gracefully
        for protocol in list(self._active_protocols):
            try:
                await protocol.stop()
            except Exception as e:
                logger.warning("Error stopping protocol: %s", e)
        self._active_protocols.clear()

        # Stop the server
        if self._server is not None:
            await self._server.__aexit__(exc_type, exc_val, exc_tb)
            self._server = None

        logger.info("DummyDAC server stopped.")

    async def _client_connected(self, reader: StreamReader, writer: StreamWriter):
        """
        Handle a new client connection.

        Creates a PassthroughTransport and Protocol instance for the connection,
        registers message handlers, and processes incoming messages until the
        connection is closed.

        :param reader: The StreamReader for the connection.
        :param writer: The StreamWriter for the connection.
        """
        peer = writer.get_extra_info("peername")
        logger.debug("DummyDAC: Client connected from %s", peer)

        # Create transport and protocol (Protocol is initialized synchronously)
        transport = await PassthroughTransport.create(reader, writer, name=str(peer))
        protocol = Protocol(IPv4Address(peer[0]), transport)

        # Track the protocol for cleanup
        self._active_protocols.add(protocol)

        # Register handlers for each command type
        for field_number, handler in self._handlers.items():
            protocol.register_callback(
                field_number,
                handler.handle,
                extra_args=[protocol]
            )

        # Start protocol and wait for it to complete
        try:
            async with protocol:
                logger.debug(
                    "DummyDAC: Protocol started for %s. Waiting for messages...", peer
                )
                await protocol
        except ConnectionError:
            # Client closed the connection - this is expected
            logger.debug("DummyDAC: Client %s disconnected.", peer)
        except Exception as e:
            logger.warning("DummyDAC: Error with client %s: %s", peer, e)
        finally:
            # Clean up
            self._active_protocols.discard(protocol)
            try:
                writer.close()
                await writer.wait_closed()
            except (BrokenPipeError, ConnectionResetError):
                # Connection already closed
                pass
            logger.debug("DummyDAC: Connection from %s cleaned up.", peer)

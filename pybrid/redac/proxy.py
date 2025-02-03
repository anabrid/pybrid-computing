# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import asyncio
import logging
from asyncio import StreamReader, StreamWriter, Server
from typing import Optional

from pybrid.base.hybrid import EntityDoesNotExist
from pybrid.base.transport import PassthroughTransport
from pybrid.redac import Controller, Path, Protocol
from pybrid.redac.protocol.messages import (
    SetCircuitRequest,
    StartRunRequest,
    SetCircuitResponse,
    StartRunResponse,
)

logger = logging.getLogger(__name__)


class Proxy:
    """
    A proxy server accepting network connections from the outside world and forwarding them as needed to the internal devices.
    """

    controller: Controller
    mac_mapping: dict[str, str]
    _server: Optional[Server]

    def __init__(
        self, controller: Controller, host: str = "localhost", port: int = 5732, mac_mapping: dict[str, str] = None
    ):
        self.controller = controller
        self.host = host
        self.port = port
        self._server = None

        self.mac_mapping = mac_mapping or {}
        for original, target in self.mac_mapping.items():
            try:
                path = Path.parse(target)
                self.controller.computer.get_entity(path)
            except EntityDoesNotExist:
                logger.warning("Target for MAC mapping from %s to %s does not exist.", original, target)

    async def client_connected(self, reader: StreamReader, writer: StreamWriter):
        peer = writer.get_extra_info("peername")
        logger.debug("Established incoming connection from %s.", peer)

        # Initiate a subordinate protocol that defaults to treating incoming messages as requests
        transport = await PassthroughTransport.create(reader, writer, name=str(peer))
        protocol = await Protocol.create(transport)
        # Register callbacks
        protocol.register_callback(SetCircuitRequest, self.handle_set_circuit, extra_args=[protocol])
        protocol.register_callback(StartRunRequest, self.handle_start_run, extra_args=[protocol])

        # Start protocol and let it process incoming messages
        async with protocol:
            logger.debug("Initiated protocol communication with %s. Waiting for incoming requests...", peer)
            await protocol

        writer.close()
        await writer.wait_closed()

    async def __aenter__(self):
        self._server = await asyncio.start_server(self.client_connected, self.host, self.port)
        await self._server.__aenter__()
        return self, self._server

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self._server.__aexit__(exc_type, exc_val, exc_tb)

    # ██   ██  █████  ███    ██ ██████  ██      ███████ ██████  ███████
    # ██   ██ ██   ██ ████   ██ ██   ██ ██      ██      ██   ██ ██
    # ███████ ███████ ██ ██  ██ ██   ██ ██      █████   ██████  ███████
    # ██   ██ ██   ██ ██  ██ ██ ██   ██ ██      ██      ██   ██      ██
    # ██   ██ ██   ██ ██   ████ ██████  ███████ ███████ ██   ██ ███████

    async def handle_set_circuit(self, msg: SetCircuitRequest, protocol: Protocol):
        logger.debug("Handling %s from %s", type(msg), protocol.transport.name)

        # Re-map carrier
        mapped_config = dict()
        for original_carrier_id, carrier_config in msg.config.items():
            mapped_config[self.mac_mapping[original_carrier_id]] = carrier_config
        # Forward
        msg.config = mapped_config
        await self.controller.forward_set_circuit(msg)

        return SetCircuitResponse()

    async def handle_start_run(self, msg: StartRunRequest, protocol: Protocol):
        logger.debug("Handling %s from %s", type(msg), protocol.transport.name)

        run = msg.to_run()
        await self.controller.start_and_await_run(run)

        return StartRunResponse()

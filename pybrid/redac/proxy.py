# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import asyncio
import json
import logging
from asyncio import StreamReader, StreamWriter, Server
from typing import Optional

from pybrid.base.hybrid import EntityDoesNotExist
from pybrid.redac import Controller, Run, Path
from pybrid.redac.protocol.envelope import Envelope
from pybrid.redac.protocol.messages import (
    SetCircuitRequest,
    ResumeSessionRequest,
    StartRunRequest,
    ResumeSessionResponse,
    SetCircuitResponse,
    StartRunResponse,
)
from pybrid.redac.protocol.types import SuccessInfo

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

        async with asyncio.timeout(10):
            envelope_in = Envelope(**json.loads((await reader.readline()).decode().strip()))
            resume_session = envelope_in.get_message(msg_class=ResumeSessionRequest)
            logger.debug("Received ResumeSessionRequest: %s", resume_session)
            envelope_out = Envelope.from_message(
                ResumeSessionResponse(success=SuccessInfo(success=True)), id_=envelope_in.id
            )
            writer.write(envelope_out.json().encode())
            writer.write(b"\n")
            await writer.drain()

        async with asyncio.timeout(10):
            envelope_in = Envelope(**json.loads((await reader.readline()).decode().strip()))
            set_circuit = envelope_in.get_message(msg_class=SetCircuitRequest)
            logger.debug("Received SetCircuitRequest: %s", set_circuit)
            logger.debug("Forwarding SetCircuitRequest...")
            await (await self.controller.forward_set_circuit(set_circuit))
            envelope_out = Envelope.from_message(SetCircuitResponse(), id_=envelope_in.id)
            writer.write(envelope_out.json().encode())
            writer.write(b"\n")
            await writer.drain()

        async with asyncio.timeout(10):
            envelope_in = Envelope(**json.loads((await reader.readline()).decode().strip()))
            start_run = envelope_in.get_message(msg_class=StartRunRequest)
            logger.debug("Received StartRunRequest: %s", start_run)
            logger.debug("Forwarding StartRunRequest...")
            run = Run(id_=start_run.id, config=start_run.config, daq=start_run.daq_config)
            await self.controller.start_and_await_run(run)
            logger.debug("Run is done.")
            envelope_out = Envelope.from_message(StartRunResponse(), id_=envelope_in.id)
            writer.write(envelope_out.json().encode())
            writer.write(b"\n")
            await writer.drain()

        writer.close()
        await writer.wait_closed()

    async def __aenter__(self):
        self._server = await asyncio.start_server(self.client_connected, self.host, self.port)
        await self._server.__aenter__()
        return self, self._server

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self._server.__aexit__(exc_type, exc_val, exc_tb)

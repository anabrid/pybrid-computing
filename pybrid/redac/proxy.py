# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import asyncio
import logging
from asyncio import StreamReader, StreamWriter, Server
from typing import Optional

from pybrid.base.hybrid import EntityDoesNotExist
from pybrid.base.transport import PassthroughTransport
from pybrid.redac import Controller, Path, Protocol, RunState
from pybrid.redac.controller import DistributedRunState
from pybrid.redac.protocol.messages import (
    SetCircuitRequest,
    StartRunRequest,
    SetCircuitResponse,
    StartRunResponse,
    GetEntitiesRequest,
    GetEntitiesResponse,
    RunStateChangeMessage,
    RunDataMessage,
    ResetCircuitRequest,
    ResetCircuitResponse,
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
        self.reverse_mac_mapping = {}
        for original, target in self.mac_mapping.items():
            self.reverse_mac_mapping[target] = original
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
        protocol.register_callback(GetEntitiesRequest, self.handle_get_entities, extra_args=[protocol])
        protocol.register_callback(ResetCircuitRequest, self.handle_reset_circuit, extra_args=[protocol])
        protocol.register_callback(SetCircuitRequest, self.handle_set_circuit, extra_args=[protocol])
        protocol.register_callback(StartRunRequest, self.handle_start_run, extra_args=[protocol])

        # Register forwarders that transparently forwards some messages (e.g. RunDataMessage)
        # But first save original ones to restore them later
        original_run_data_handlers = {
            protocol_: protocol_.get_callback(RunDataMessage) for protocol_ in self.controller.protocols
        }
        for protocol_ in self.controller.protocols:
            protocol_.register_callback(
                RunDataMessage, self.forward_run_data, extra_args=[protocol, protocol_.get_callback(RunDataMessage)]
            )

        # Start protocol and let it process incoming messages
        async with protocol:
            logger.debug("Initiated protocol communication with %s. Waiting for incoming requests...", peer)
            await protocol

        writer.close()
        await writer.wait_closed()

        # Restore original handlers
        for protocol_, (handler, args, kwargs) in original_run_data_handlers.items():
            protocol_.register_callback(RunDataMessage, handler, extra_args=args, extra_kwargs=kwargs)

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

    # Handlers handle incoming requests from the client side

    async def handle_get_entities(self, msg: GetEntitiesRequest, protocol: Protocol):
        logger.debug("Handling %s from %s", type(msg), protocol.transport.name)
        mapped_raw_entity_dict = {
            self.reverse_mac_mapping[key.strip("/")]: value for key, value in self.controller._raw_entity_dict.items()
        }
        return GetEntitiesResponse(entities=mapped_raw_entity_dict)

    async def handle_reset_circuit(self, msg: ResetCircuitRequest, protocol: Protocol):
        logger.debug("Handling %s from %s", type(msg), protocol.transport.name)
        await self.controller.reset(keep_calibration=msg.keep_calibration, sync=msg.sync)
        return ResetCircuitResponse()

    async def handle_set_circuit(self, msg: SetCircuitRequest, protocol: Protocol):
        logger.debug("Handling %s from %s", type(msg), protocol.transport.name)

        # The message may contain an entity path that we need to prepend
        if msg.entity:
            assert len(msg.entity) == 1, "Not implemented yet."
            config = {msg.entity[0]: msg.config}
        else:
            config = msg.config

        # Re-map carrier
        mapped_config = dict()
        for original_carrier_id, carrier_config in config.items():
            mapped_config[self.mac_mapping[original_carrier_id]] = carrier_config
        # Forward
        msg.config = mapped_config
        await self.controller.forward_set_circuit(msg)

        return SetCircuitResponse()

    async def monitor_run_state(self, run_state: DistributedRunState, protocol: Protocol):
        await asyncio.wait_for(run_state.wait_all(RunState.TAKE_OFF), timeout=3)
        await protocol.send_message(
            RunStateChangeMessage(id=run_state.run.id_, t=0, old=RunState.NEW, new=RunState.TAKE_OFF)
        )
        await asyncio.wait_for(run_state.wait_all(RunState.DONE), timeout=3)
        await protocol.send_message(
            RunStateChangeMessage(id=run_state.run.id_, t=0, old=RunState.TAKE_OFF, new=RunState.DONE)
        )

    async def handle_start_run(self, msg: StartRunRequest, protocol: Protocol):
        logger.debug("Handling %s from %s", type(msg), protocol.transport.name)

        run = msg.to_run()
        run_state = await self.controller.start_run(run)
        asyncio.create_task(self.monitor_run_state(run_state, protocol))

        return StartRunResponse()

    # ███████  ██████  ██████  ██     ██  █████  ██████  ██████  ███████ ██████  ███████
    # ██      ██    ██ ██   ██ ██     ██ ██   ██ ██   ██ ██   ██ ██      ██   ██ ██
    # █████   ██    ██ ██████  ██  █  ██ ███████ ██████  ██   ██ █████   ██████  ███████
    # ██      ██    ██ ██   ██ ██ ███ ██ ██   ██ ██   ██ ██   ██ ██      ██   ██      ██
    # ██       ██████  ██   ██  ███ ███  ██   ██ ██   ██ ██████  ███████ ██   ██ ███████

    # Forwarders transparently "copy" messages from the mREDACs towards the client

    async def forward_run_data(self, msg: RunDataMessage, protocol: Protocol, original_handler_info):
        logger.debug("Handling %s from %s", type(msg), protocol.transport.name)
        if original_handler_info:
            await original_handler_info[0](msg, *original_handler_info[1], **original_handler_info[2])
        await protocol.send_message(msg)

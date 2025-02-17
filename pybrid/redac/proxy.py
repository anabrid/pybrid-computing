# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import asyncio
import logging
from asyncio import StreamReader, StreamWriter, Server
from typing import Optional
from weakref import WeakValueDictionary

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
    GetPartitionInformationRequest,
    GetPartitionInformationResponse,
    SysTemperaturesRequest,
    SysTemperaturesResponse,
)

logger = logging.getLogger(__name__)


class Proxy:
    """
    A proxy server accepting network connections from the outside world and forwarding them as needed to the internal devices.
    """

    controller: Controller
    mac_mapping: dict[str, str]
    _server: Optional[Server]

    _path_to_client: WeakValueDictionary[Path, Protocol]

    def __init__(
        self,
        controller: Controller,
        host: str = "localhost",
        port: int = 5732,
        mac_mapping: dict[str, str] = None,
        partition_config: dict = {},
        mode: str = "carrier",
    ):
        self.controller = controller
        self.controller.enable_sync()

        self.host = host
        self.port = port
        self._server = None

        ###
        # Note: The proxy maps virtual MACs to entity MACs. However, when users
        # query information about the system in total, ther eis no point in returning
        # those addresses - since, when partitioned, every partition has a
        # MAC 00-00-00-00-00-00.
        # Hence, when showing system state, we stick to the hardware macs.
        ###
        self.mac_mapping = mac_mapping or {}
        self.reverse_mac_mapping = {}

        for original, target in self.mac_mapping.items():
            self.reverse_mac_mapping[target] = original
            try:
                path = Path.parse(target)
                self.controller.computer.get_entity(path)
            except EntityDoesNotExist:
                logger.warning("Target for MAC mapping from %s to %s does not exist.", original, target)

        self.partition_mode = mode
        self.partition_config = partition_config[mode]

        # We need to forward certain messages from the mREDACs to clients
        self._path_to_client = WeakValueDictionary()
        for protocol in self.controller.protocols:
            protocol.register_callback(RunDataMessage, self.forward_run_data, extra_args=[protocol])

    async def __aenter__(self):
        self._server = await asyncio.start_server(self.client_connected, self.host, self.port)
        await self._server.__aenter__()
        return self, self._server

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self._server.__aexit__(exc_type, exc_val, exc_tb)

    #  ██████ ██      ██ ███████ ███    ██ ████████ ███████
    # ██      ██      ██ ██      ████   ██    ██    ██
    # ██      ██      ██ █████   ██ ██  ██    ██    ███████
    # ██      ██      ██ ██      ██  ██ ██    ██         ██
    #  ██████ ███████ ██ ███████ ██   ████    ██    ███████

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
        protocol.register_callback(
            GetPartitionInformationRequest, self.handle_partition_information, extra_args=[protocol]
        )
        protocol.register_callback(SysTemperaturesRequest, self.handle_temperature_request, extra_args=[protocol])

        # Start protocol and let it process incoming messages
        try:
            async with protocol:
                logger.debug("Initiated protocol communication with %s. Waiting for incoming requests...", peer)
                await protocol
        except ConnectionError:
            # Client closed the connection
            pass
        try:
            writer.close()
            await writer.wait_closed()
        except BrokenPipeError:
            # Client closed the connection already
            pass

    def get_client_controlling_path(self, path: Path):
        return self._path_to_client[path]

    def set_client_controlling_path(self, protocol: Protocol, path: Path):
        self._path_to_client[path] = protocol

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
        try:
            await asyncio.wait_for(run_state.wait_all(RunState.TAKE_OFF), timeout=3)
        except Exception as e:
            logger.exception(e)
            return
        await protocol.send_message(
            RunStateChangeMessage(id=run_state.run.id_, t=0, old=RunState.NEW, new=RunState.TAKE_OFF)
        )
        self.controller.sync.trigger(42)
        try:
            await asyncio.wait_for(run_state.wait_all(RunState.DONE), timeout=3)
        except Exception as e:
            logger.exception(e)
        await protocol.send_message(
            RunStateChangeMessage(id=run_state.run.id_, t=0, old=RunState.TAKE_OFF, new=RunState.DONE)
        )

    async def handle_start_run(self, msg: StartRunRequest, protocol: Protocol):
        logger.debug("Handling %s from %s", type(msg), protocol.transport.name)

        run = msg.to_run()
        run_state = await self.controller.start_run(run)

        for path in run_state.get_invovlved_paths():
            self.set_client_controlling_path(protocol, Path.parse(self.reverse_mac_mapping[path.id_]))
        asyncio.create_task(self.monitor_run_state(run_state, protocol))

        return StartRunResponse()

    async def handle_partition_information(self, msg: GetPartitionInformationRequest, protocol: Protocol):
        logger.debug("Handling %s from %s", type(msg), protocol.transport.name)

        return GetPartitionInformationResponse(partition_mode=self.partition_mode, entities=self.partition_config)

    async def handle_temperature_request(self, msg: SysTemperaturesRequest, protocol: Protocol):
        logger.debug("Handling %s from %s", type(msg), protocol.transport.name)

        hw_response = await self.controller.get_system_temperatures()
        mapped_response = {self.reverse_mac_mapping[k[0]]: v for (k, v) in hw_response.items()}

        return SysTemperaturesResponse(entities=mapped_response)

    # ███████  ██████  ██████  ██     ██  █████  ██████  ██████  ███████ ██████  ███████
    # ██      ██    ██ ██   ██ ██     ██ ██   ██ ██   ██ ██   ██ ██      ██   ██ ██
    # █████   ██    ██ ██████  ██  █  ██ ███████ ██████  ██   ██ █████   ██████  ███████
    # ██      ██    ██ ██   ██ ██ ███ ██ ██   ██ ██   ██ ██   ██ ██      ██   ██      ██
    # ██       ██████  ██   ██  ███ ███  ██   ██ ██   ██ ██████  ███████ ██   ██ ███████

    # Forwarders transparently "copy" messages from the mREDACs towards the client

    async def forward_run_data(self, msg: RunDataMessage, protocol: Protocol):
        # protocol is the connection to the source of the data
        logger.debug("Forwarding %s from %s", type(msg), protocol.transport.name)

        msg_ = msg.copy()
        msg_.entity = (self.reverse_mac_mapping[msg_.entity[0]], msg_.entity[1])

        # Forward data to client in control of the source
        try:
            client = self.get_client_controlling_path(Path.parse(msg_.entity[0]))
            await client.send_message(msg)
        except KeyError:
            logger.warning("No client interested in incoming data from %s", protocol.transport.name)
        except BrokenPipeError:
            # Client disconnected
            pass
        except Exception as e:
            logger.exception(e)

# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import asyncio
import logging
import warnings
from asyncio import StreamReader, StreamWriter, Server
from ipaddress import IPv4Address
from typing import Optional
from weakref import WeakValueDictionary, WeakKeyDictionary

from pybrid.base.hybrid import EntityDoesNotExist
from pybrid.base.transport import PassthroughTransport
from pybrid.redac import Controller, Path, Protocol, RunState
from pybrid.redac.controller import DistributedRunState
from pybrid.redac.partitioning import PartitionConfig
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
    SysTemperaturesResponse, RegisterExternalEntitiesRequest, RegisterExternalEntitiesResponse,
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
    _client_to_partition: WeakKeyDictionary[Protocol, PartitionConfig]

    _partitioning: dict[str, list[list]]

    def __init__(
        self,
        controller: Controller,
        host: str = "localhost",
        port: int = 5732,
        mac_mapping: dict[str, str] = None,
        partition_config: dict = {},
        mode: str = "device",
    ):
        self.controller = controller
        if not self.controller.standalone:
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

        self.partitioning = partition_config
        self.partition_mode = mode
        self.partitions = partition_config[mode]
        self._client_to_partition = WeakKeyDictionary()

        # We need to forward certain messages from the mREDACs to clients
        self._path_to_client = WeakValueDictionary()
        for protocol in self.controller.protocols:
            protocol.register_callback(RunDataMessage, self.forward_run_data, extra_args=[protocol])

    async def __aenter__(self):
        # Register the virtualized external entities with everyone
        # TODO: This needs to not only happen once, but everytime Controller.add_device is called
        await self._register_virtualized_external_entities()
        self._server = await asyncio.start_server(self.client_connected, self.host, self.port)
        await self._server.__aenter__()
        return self, self._server

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self._server.__aexit__(exc_type, exc_val, exc_tb)

    # ███    ███ ██ ███████  ██████
    # ████  ████ ██ ██      ██
    # ██ ████ ██ ██ ███████ ██
    # ██  ██  ██ ██      ██ ██
    # ██      ██ ██ ███████  ██████

    async def _register_virtualized_external_entities(self):
        virtual_external_entities: dict[str, IPv4Address] = {}
        # Collect
        for protocol, paths in self.controller.protocols.items():
            for path in paths:
                if virtual_id := self.reverse_mac_mapping.get(path.id_, None):
                    virtual_external_entities[virtual_id] = protocol.transport.get_remote_ip()
                else:
                    warnings.warn(f"Can not register virtual external entity for path {path}.")
        # Register
        # Note that we also register the virtualized "self", which should not matter
        for protocol in self.controller.protocols:
            await protocol.register_external_entities(virtual_external_entities)


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
        protocol.register_callback(RegisterExternalEntitiesRequest, self.handle_register_external_entities_request, extra_args=[protocol])

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

    def get_client_partition(self, protocol: Protocol) -> PartitionConfig:
        return self._client_to_partition[protocol]

    def set_client_partition(self, protocol: Protocol, partition: PartitionConfig):
        self._client_to_partition[protocol] = partition

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

        if msg.partition_config:
            # Re-map from partition-local to global virtual ids
            config = {msg.partition_config.remap_virtual_entity_id(key_): value_ for key_, value_ in config.items()}

        # Re-map from virtual to real entity ids
        mapped_config = dict()
        for original_carrier_id, carrier_config in config.items():
            mapped_config[self.mac_mapping[original_carrier_id]] = carrier_config
        # Forward
        msg.config = mapped_config
        await self.controller.forward_set_circuit(msg)

        return SetCircuitResponse()

    async def monitor_run_state(self, run_state: DistributedRunState, protocol: Protocol):
        try:
            async with asyncio.timeout(3):
                await run_state.wait_all(RunState.TAKE_OFF)
        except Exception as e:
            logger.exception(e)
            await protocol.send_message(
                RunStateChangeMessage(id=run_state.run.id_, t=0, old=RunState.NEW, new=RunState.ERROR, reason=str(e))
            )
            return
        await protocol.send_message(
            RunStateChangeMessage(id=run_state.run.id_, t=0, old=RunState.NEW, new=RunState.TAKE_OFF)
        )
        if not self.controller.standalone:
            self.controller.sync.trigger(run_state.run.sync.group)
        try:
            async with asyncio.timeout(10):
                await run_state.wait_all(RunState.DONE)
        except Exception as e:
            logger.exception(e)
            await protocol.send_message(
                RunStateChangeMessage(
                    id=run_state.run.id_, t=0, old=RunState.TAKE_OFF, new=RunState.ERROR, reason=str(e)
                )
            )
            return
        await protocol.send_message(
            RunStateChangeMessage(id=run_state.run.id_, t=0, old=RunState.TAKE_OFF, new=RunState.DONE)
        )

    async def handle_start_run(self, msg: StartRunRequest, protocol: Protocol):
        logger.debug("Handling %s from %s", type(msg), protocol.transport.name)

        devices = self.partitions[msg.partition_config.id]
        mapped_devices = [self.mac_mapping[device] for device in devices]
        mapped_paths = [Path.parse(device) for device in mapped_devices]
        logger.debug("Incoming StartRunRequest is relevant for %s", mapped_paths)

        run = msg.to_run()
        run_state = await self.controller.start_run(run, mapped_paths)

        # Remember stuff about the client
        self.set_client_partition(protocol, msg.partition_config)
        for path in run_state.get_invovlved_paths():
            self.set_client_controlling_path(protocol, path)
        # Monitor run state
        # TODO: This is really cumbersome to have as a task...
        asyncio.create_task(self.monitor_run_state(run_state, protocol))

        return StartRunResponse()

    async def handle_partition_information(self, msg: GetPartitionInformationRequest, protocol: Protocol):
        logger.debug("Handling %s from %s", type(msg), protocol.transport.name)

        return GetPartitionInformationResponse(partition_mode=self.partition_mode, entities=self.partitions)

    async def handle_temperature_request(self, msg: SysTemperaturesRequest, protocol: Protocol):
        logger.debug("Handling %s from %s", type(msg), protocol.transport.name)

        hw_response = await self.controller.get_system_temperatures()
        mapped_response = {self.reverse_mac_mapping[k[0]]: v for (k, v) in hw_response.items()}

        return SysTemperaturesResponse(entities=mapped_response)

    async def handle_register_external_entities_request(self, msg: RegisterExternalEntitiesRequest, protocol: Protocol):
        # This request does not need to be forwarded, as the proxy currently only works with
        # virtualized entity ids which are already registered. So just do nothing.
        return RegisterExternalEntitiesResponse()

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

        # Forward data to client in control of the source
        try:
            client = self.get_client_controlling_path(Path.parse(msg_.entity[0]))
        except KeyError:
            logger.warning("No client interested in incoming data from %s", protocol.transport.name)
            return
        except BrokenPipeError:
            # Client disconnected
            return
        except Exception as e:
            logger.exception(e)
            return

        # Map from real to global virtual entity ids
        # NOTE: len(msg.entity) == 1 if ms.state == OP_END, otherwise its length is two
        msg_.entity = (self.reverse_mac_mapping[msg_.entity[0]],) + msg_.entity[1:]

        try:
            # Map from global virtual entity ids to partition-local ones
            partition_config = self.get_client_partition(client)
        except KeyError:
            # Client doesn't care about partitions
            pass
        except Exception as e:
            logger.exception(e)
        else:
            # NOTE: len(msg.entity) == 1 if ms.state == OP_END, otherwise its length is two
            msg_.entity = (partition_config.inv_remap_virtual_entity_id(msg_.entity[0]),) + msg_.entity[1:]

        await client.send_message(msg_)

# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import asyncio
import logging
import warnings
from asyncio import StreamReader, StreamWriter, Server
from ipaddress import IPv4Address
from typing import Optional
from uuid import UUID
from weakref import WeakValueDictionary, WeakKeyDictionary

import pybrid.base.proto.main_pb2 as pb

from pybrid.base.hybrid import EntityDoesNotExist
from pybrid.base.transport import PassthroughTransport
from pybrid.base.transport.udp import UDPTransport
from pybrid.redac import Controller, Path, Protocol, RunState, Run, RunConfig, DAQConfig
from pybrid.redac.controller import DistributedRunState
from pybrid.redac.partitioning import PartitionConfig
from pybrid.redac.port import get_free_udp_port
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
from pybrid.base.proto import main_pb2
from pybrid.redac.protocol.receiver import Receiver
from pybrid.redac.run import CalibrationConfig
from pybrid.redac.sync import SyncConfig

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
        # query information about the system in total, there is no point in returning
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

        #self.controller.register_callback()
        for protocol in self.controller.protocols:
            protocol.register_callback(pb.MessageV1.RUN_DATA_MESSAGE_FIELD_NUMBER, self.forward_run_data, extra_args=[protocol])
            protocol.register_callback(pb.MessageV1.RUN_DATA_END_MESSAGE_FIELD_NUMBER, self.forward_run_data, extra_args=[protocol])

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
                    virtual_external_entities[virtual_id] = protocol.ctrl_transport.get_remote_ip()
                else:
                    warnings.warn(f"Can not register virtual external entity for path {path}.")
        # Register
        # Note that we also register the virtualized "self", which should not matter
        #TODO
        #for protocol in self.controller.protocols:
        #    await protocol.register_external_entities(virtual_external_entities)


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
        protocol = await Protocol.create(IPv4Address(peer[0]), transport)

        # Register callbacks
        protocol.register_callback(pb.MessageV1.DESCRIBE_COMMAND_FIELD_NUMBER, self.handle_get_entities, extra_args=[protocol])
        protocol.register_callback(pb.MessageV1.RESET_COMMAND_FIELD_NUMBER, self.handle_reset_config, extra_args=[protocol])
        protocol.register_callback(pb.MessageV1.CONFIG_COMMAND_FIELD_NUMBER, self.handle_set_config, extra_args=[protocol])
        protocol.register_callback(pb.MessageV1.EXTRACT_COMMAND_FIELD_NUMBER, self.handle_get_config, extra_args=[protocol])
        protocol.register_callback(pb.MessageV1.START_RUN_COMMAND_FIELD_NUMBER, self.handle_start_run, extra_args=[protocol])
        protocol.register_callback(pb.MessageV1.UDP_DATA_STREAMING_COMMAND_FIELD_NUMBER, self.handle_udp_data_streaming, extra_args=[protocol])
        #protocol.register_callback(
        #    GetPartitionInformationRequest, self.handle_partition_information, extra_args=[protocol]
        #)
        #protocol.register_callback(SysTemperaturesRequest, self.handle_temperature_request, extra_args=[protocol])
        protocol.register_callback(pb.MessageV1.REGISTER_EXTERNAL_ENTITIES_COMMAND_FIELD_NUMBER, self.handle_register_external_entities_request, extra_args=[protocol])

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

    async def handle_get_entities(self, msg: pb.DescribeCommand, protocol: Protocol):
        logger.debug("Handling %s from %s", type(msg), protocol.ctrl_transport.name)
        carriers = []
        for carrier in self.controller._raw_entity_dict.values():
            entity = pb.Entity()
            entity.CopyFrom(carrier)  # deep copy carrier into new entity
            entity.id = self.reverse_mac_mapping[carrier.id.strip("/")]  # override id
            carriers.append(entity)

        machine = pb.Entity(id="/", class_=pb.Entity.Class.DEVICE, children=carriers)
        return pb.DescribeResponse(entity=machine)

    async def handle_reset_config(self, msg: pb.ResetCommand, protocol: Protocol):
        logger.debug("Handling %s from %s", type(msg), protocol.ctrl_transport.name)
        await self.controller.reset(keep_calibration=msg.keep_calibration, sync=msg.sync)
        return pb.ResetResponse()

    async def handle_get_config(self, msg: pb.ExtractCommand, protocol: Protocol):
        path = Path.parse(msg.entity.path)
        is_root = len(path) == 0
        if is_root:
            devices = self.controller.devices.values()
        else:
            devices = [self.controller.devices[path.to_root()]]

        response_setup = pb.ConfigBundle()
        for device in devices:
            if not is_root:
                path = Path() / self.mac_mapping[path[0]] / path[1:]
            bundle = await device.protocol.get_config(path, msg.recursive)

            for config in bundle.configs:
                entity_path = Path.parse(config.entity.path)
                config.entity.path = str(Path() / self.reverse_mac_mapping[entity_path[0]] / entity_path[1:])
            response_setup.configs.extend(bundle.configs)
        return pb.ExtractResponse(bundle=response_setup)

    def _foreach_protocol(self, fn):
        forwards = (fn(target) for target in self.controller.protocols.keys())
        return asyncio.gather(*forwards)

    async def handle_set_config(self, msg: pb.ConfigCommand, protocol: Protocol):
        logger.debug("Handling %s", type(msg))

        # The message may contain an entity path that we need to prepend
        #if msg.entity:
        #    assert len(msg.entity) == 1, "Not implemented yet."
        #    config = {msg.entity[0]: msg.config}
        #else:
        #    config = msg.config

        #if msg.partition_config:
        #    # Re-map from partition-local to global virtual ids
        #    config = {msg.partition_config.remap_virtual_entity_id(key_): value_ for key_, value_ in config.items()}

        # Re-map from virtual to real entity ids
        mapped_config = dict()
        for config in msg.bundle.configs:
            entity_path = Path.parse(config.entity.path)
            carrier_mac = entity_path[0]
            mac = self.mac_mapping[carrier_mac]
            new_entity_path = Path() / mac / entity_path[1:]
            config.entity.path = str(new_entity_path)
            if mac not in mapped_config:
                configs = list()
                mapped_config[mac] = configs
            else:
                configs = mapped_config[mac]
            configs.append(config)

        msg.bundle.configs.clear()

        protocol2cmd = dict()
        for protocol, paths in self.controller.protocols.items():
            new_cmd = pb.ConfigCommand()
            new_cmd.CopyFrom(msg)
            for path in paths:
                carrier_mac = path[0]
                if carrier_mac not in mapped_config:
                    continue

                new_cmd.bundle.configs.extend(mapped_config[carrier_mac])
            protocol2cmd[protocol] = new_cmd

        forwards = (Protocol.send_body_and_wait_response.__get__(protocol, protocol.__class__)(cmd=protocol2cmd[protocol]) for protocol in self.controller.protocols)
        results = await asyncio.gather(*forwards)
        return pb.ConfigResponse()

    async def monitor_run_state(self, run_state: DistributedRunState, protocol: Protocol):
        zero_time = pb.Time(value=0, prefix=pb.Prefix.NONE)
        try:
            async with asyncio.timeout(3):
                await run_state.wait_all(RunState.TAKE_OFF)
        except Exception as e:
            logger.exception(e)
            await protocol.send_body_with_response(
                pb.RunStateChangeMessage(run_id=str(run_state.run.id_), time=zero_time, old=pb.RunState.NEW,
                                         new_=pb.RunState.ERROR, reason=str(e)))
            return
        await protocol.send_body_with_response(
            pb.RunStateChangeMessage(run_id=str(run_state.run.id_), time=zero_time, old=pb.RunState.NEW,
                                     new_=pb.RunState.TAKE_OFF))
        if not self.controller.standalone:
            self.controller.sync.trigger(run_state.run.sync.group)
        try:
            async with asyncio.timeout(10):
                await run_state.wait_all(RunState.DONE)
        except Exception as e:
            logger.exception(e)
            await protocol.send_body_with_response(pb.RunStateChangeMessage(
                run_id=str(run_state.run.id_), time=zero_time, old=pb.RunState.TAKE_OFF, new_=pb.RunState.ERROR,
                reason=str(e)
            ))
            return
        await protocol.send_body_with_response(
            pb.RunStateChangeMessage(run_id=str(run_state.run.id_), time=zero_time, old=pb.RunState.TAKE_OFF,
                                     new_=pb.RunState.DONE))

    @staticmethod
    def time_to_nanos(time: pb.Time) -> int:
        if time.prefix == pb.Prefix.NANO:
            return time.value
        if time.prefix == pb.Prefix.MICRO:
            return time.value * 1_000
        if time.prefix == pb.Prefix.MILLI:
            return time.value * 1_000_000
        if time.prefix == pb.Prefix.NONE:
            return time.value * 1_000_000_000

        return 0

    async def handle_udp_data_streaming(self, msg: pb.UdpDataStreamingCommand, client_protocol: Protocol):
        for protocol in self.controller.protocols:
            free_port = get_free_udp_port(6733)
            response = await protocol.udp_data_streaming(free_port)
            if response.WhichOneof("kind") != "success_message":
                return response

        await client_protocol.udp_data_receiving(port = msg.port)
        return pb.SuccessMessage()

    async def test(msg):
        pass

    async def handle_start_run(self, msg: pb.StartRunCommand, protocol: Protocol):
        logger.debug("Handling %s from %s", type(msg), protocol.ctrl_transport.name)

        #devices = self.partitions[msg.partition_config.id]
        #mapped_devices = [self.mac_mapping[device] for device in devices]
        #mapped_paths = [Path.parse(device) for device in mapped_devices]
        #logger.debug("Incoming StartRunRequest is relevant for %s", mapped_paths
        mapped_paths = None

        #run = msg.to_run()

        run = Run(
            id_=UUID(msg.run_id),
            config=RunConfig(
                ic_time=self.time_to_nanos(msg.run_config.ic_time),
                op_time=self.time_to_nanos(msg.run_config.op_time)
            ),
            daq=DAQConfig(
                num_channels=msg.daq_config.num_channels,
                sample_rate=msg.daq_config.sample_rate,
                sample_op=msg.daq_config.sample_op,
                sample_op_end=msg.daq_config.sample_op_end,
            ),
            sync=SyncConfig(
                enabled=msg.sync_config.enabled,
                master=None if not msg.sync_config.HasField("master") else Path.parse(
                    self.mac_mapping[msg.sync_config.master.path]),
                group=msg.sync_config.group,
            ),
            calibration=CalibrationConfig(
                enabled=msg.calibration_config.enabled,
                leader=None if not msg.calibration_config.HasField("leader") else Path.parse(
                    self.mac_mapping[msg.calibration_config.leader.path]),
            ),
            partition=PartitionConfig(),
        )

        run_state = await self.controller.start_run(run, mapped_paths)

        # Remember stuff about the client
        #self.set_client_partition(protocol, msg.partition_config)
        for path in run_state.get_involved_paths():
            self.set_client_controlling_path(protocol, path)
        # Monitor run state
        # TODO: This is really cumbersome to have as a task...
        asyncio.create_task(self.monitor_run_state(run_state, protocol))
        return pb.StartRunResponse()

    async def handle_partition_information(self, msg: GetPartitionInformationRequest, protocol: Protocol):
        logger.debug("Handling %s from %s", type(msg), protocol.ctrl_transport.name)

        return GetPartitionInformationResponse(partition_mode=self.partition_mode, entities=self.partitions)

    async def handle_temperature_request(self, msg: SysTemperaturesRequest, protocol: Protocol):
        logger.debug("Handling %s from %s", type(msg), protocol.ctrl_transport.name)

        hw_response = await self.controller.get_system_temperatures()
        mapped_response = {self.reverse_mac_mapping[k[0]]: v for (k, v) in hw_response.items()}

        return SysTemperaturesResponse(entities=mapped_response)

    async def handle_register_external_entities_request(self, msg: RegisterExternalEntitiesRequest, protocol: Protocol):
        # This request does not need to be forwarded, as the proxy currently only works with
        # virtualized entity ids which are already registered. So just do nothing.
        return pb.SuccessMessage()

    # ███████  ██████  ██████  ██     ██  █████  ██████  ██████  ███████ ██████  ███████
    # ██      ██    ██ ██   ██ ██     ██ ██   ██ ██   ██ ██   ██ ██      ██   ██ ██
    # █████   ██    ██ ██████  ██  █  ██ ███████ ██████  ██   ██ █████   ██████  ███████
    # ██      ██    ██ ██   ██ ██ ███ ██ ██   ██ ██   ██ ██   ██ ██      ██   ██      ██
    # ██       ██████  ██   ██  ███ ███  ██   ██ ██   ██ ██████  ███████ ██   ██ ███████

    # Forwarders transparently "copy" messages from the mREDACs towards the client

    async def forward_run_data(self, msg: pb.RunDataMessage | pb.RunDataEndMessage, protocol: Protocol):
        # protocol is the connection to the source of the data
        logger.debug("Forwarding %s", type(msg))

        # Forward data to client in control of the source
        try:
            path = Path.parse(msg.entity.path)
            client = self.get_client_controlling_path(path.to_root())
        except KeyError:
            logger.warning("No client interested in incoming data")
            return
        except BrokenPipeError:
            # Client disconnected
            return
        except Exception as e:
            logger.exception(e)
            return

        # Map from real to global virtual entity ids
        # NOTE: len(msg.entity) == 1 if ms.state == OP_END, otherwise its length is two
        msg.entity.path = str(Path() / self.reverse_mac_mapping[path[0]] / path[1:])

        #try:
        #    # Map from global virtual entity ids to partition-local ones
        #    partition_config = self.get_client_partition(client)
        #except KeyError:
        #    # Client doesn't care about partitions
        #    pass
        #except Exception as e:
        #    logger.exception(e)
        #else:
        #    # NOTE: len(msg.entity) == 1 if ms.state == OP_END, otherwise its length is two
        #    msg.entity = (partition_config.inv_remap_virtual_entity_id(msg.entity[0]),) + msg.entity.path[1:]

        await client.send_body_with_response(msg)


# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import asyncio
import json
import logging
import os
import sys
import time
import typing
import uuid
from asyncio import tasks
from ipaddress import IPv4Address
from typing import Callable

from packaging.version import Version

from pybrid.base.hybrid.protocol import (
    BaseProtocol,
    ProtocolError,
    MalformedDataError,
    UnsuccessfulRequestError,
)
from pybrid.base.transport import StreamTransport, TCPTransport
from .envelope import Envelope
from .messages import (
    Message,
    Notification,
    Request,
    Response,
    GetEntitiesRequest,
    GetCircuitRequest,
    SetCircuitRequest,
    StartRunRequest,
    HackRequest,
    SetDAQRequest,
    ResetCircuitRequest,
    GetStatusRequest,
    SysTemperaturesRequest,
    SetStandbyRequest,
    SysRebootRequest,
    RegisterExternalEntitiesRequest,
)
from .receiver import Receiver
from .serializer import build_config
from ..controller import get_free_udp_port
from ..entities import Path, Entity
from ..partitioning import PartitionConfig
from ..run import RunConfig, DAQConfig, CalibrationConfig
from ..sync import SyncConfig, SyncMode

from uuid import UUID, uuid4

from google.protobuf.json_format import MessageToJson
from google.protobuf.internal import encoder
from google.protobuf.internal import decoder
import pybrid.base.proto.main_pb2 as pb
from ...base.transport.base import BaseTransport
from ...base.transport.udp import UDPTransport

logger = logging.getLogger(__name__)

def find_first(lst, condition):
    return next(filter(condition, lst), None)

def get_message_kind(msg: pb.MessageV1) -> str | None :
    try:
        return msg.WhichOneof("kind")
    except:
        logger.warning("No message type present.")
        return None

class Protocol(BaseProtocol):
    receive_loops : typing.List[tasks.Task] = []
    remote_address : IPv4Address
    ctrl_transport : BaseTransport = None
    data_transport : BaseTransport = None
    ctrl_receiver : Receiver | None = None
    data_receiver : Receiver | None = None

    def __init__(self, remote_address: IPv4Address, ctrl_transport: BaseTransport, version: Version = None):
        super().__init__(version)
        self.remote_address = remote_address
        self.ctrl_transport = ctrl_transport
        self.ctrl_receiver = Receiver(ctrl_transport, lambda msg: self.process(msg))
        self._expected_responses: dict[UUID, asyncio.futures.Future] = dict()
        self._callbacks: dict[int, tuple[Callable, list, dict]] = dict()

    def get_remote_address(self):
        return self.remote_address

    async def start(self):
        await self.ctrl_receiver.start()

    async def stop(self):
        self.ctrl_transport.close()
        await self.ctrl_receiver.stop()
        if self.data_receiver:
            self.data_transport.close()
            await self.data_receiver.stop()

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()

    def __await__(self):
        return self.ctrl_receiver.__await__()

    # ███████ ███████ ███    ██ ██████  ██ ███    ██  ██████
    # ██      ██      ████   ██ ██   ██ ██ ████   ██ ██
    # ███████ █████   ██ ██  ██ ██   ██ ██ ██ ██  ██ ██   ███
    #      ██ ██      ██  ██ ██ ██   ██ ██ ██  ██ ██ ██    ██
    # ███████ ███████ ██   ████ ██████  ██ ██   ████  ██████

                                #, meta: typing.Optional[dict] = None
    async def send_message(self, msg):
        #envelope_mod = envelope

        # TODO: same as below, find a nicer way for the hack
        #if meta:
        #    envelope_mod.msg['meta'] = meta

        logger.debug("sending: %s", MessageToJson(msg, always_print_fields_with_no_presence=True))
        envelope = pb.Envelope(message_v1=msg)

        if msg.WhichOneof("kind") in ["run_data_message", "run_data_end_message", "run_state_change_message"]:
            transport = self.data_transport if self.data_transport is not None else self.ctrl_transport
        else:
            transport = self.ctrl_transport

        data = envelope.SerializeToString()
        await transport.send_packet(data)

    async def send_body_and_wait_response(self, cmd):
        response_fut = await self.send_body_with_response(cmd)
        response = await response_fut
        return response

    async def send_message_with_response(self, msg: pb.MessageV1):

        # Generate an future
        response_future = asyncio.get_event_loop().create_future()

        # A response is only expected for requests
        self._expected_responses[UUID(msg.id)] = response_future

        # TODO: remove this hack and find a better way to add authentication
        #meta = None
        #bearer = os.getenv("PYBRID_META_AUTHENTICATION", None)
        #if bearer:
        #    meta = {
        #        "Authorization": f"Bearer {bearer}"
        #    }

        await self.send_message(msg)
        # Return future to response
        return response_future

    @staticmethod
    def new_message(body, id = None):
        if id is None:
            id = uuid4()

        if isinstance(id, UUID):
            id = str(id)

        msg = pb.MessageV1(id=id)
        fields = msg.DESCRIPTOR.oneofs_by_name.get("kind").fields
        field = find_first(fields, lambda field: field.message_type == body.DESCRIPTOR)
        if field is None:
            raise ProtocolError(f"No message type found for {body}")

        getattr(msg, field.name).CopyFrom(body)
        return msg

    async def send_body_with_response(self, body):
        return await self.send_message_with_response(Protocol.new_message(body))

    async def send_error(self, msg_id : str | UUID, description: str):
        if isinstance(msg_id, UUID):
            msg_id = str(msg_id)

        await self.send_message(pb.MessageV1(id=msg_id, error_message=pb.ErrorMessage(description=description)))



    #  ██████  █████  ██      ██      ██████   █████   ██████ ██   ██ ███████
    # ██      ██   ██ ██      ██      ██   ██ ██   ██ ██      ██  ██  ██
    # ██      ███████ ██      ██      ██████  ███████ ██      █████   ███████
    # ██      ██   ██ ██      ██      ██   ██ ██   ██ ██      ██  ██       ██
    #  ██████ ██   ██ ███████ ███████ ██████  ██   ██  ██████ ██   ██ ███████

    def register_callback(self, msg_type: int, callback: Callable, extra_args=None, extra_kwargs=None):
        previous = self._callbacks.get(msg_type, None)
        self._callbacks[msg_type] = (callback, extra_args or list(), extra_kwargs or dict())
        return previous

    def get_callback(self, msg_type: int):
        return self._callbacks.get(msg_type, None)


    async def process(self, msg: pb.MessageV1):
        if msg.id is None or len(msg.id) == 0:
            # Incoming message is a notification
            try:
                response = await self.do_callback(msg)
            except Exception as exc:
                logger.exception("Error during callback for %s: %s", str(msg.id), exc)
            else:
                if response is not None:
                    logger.warning("Return values of notification callback handlers are ignored.")
        else:
            id = UUID(msg.id)

            if id in self._expected_responses:
                # Incoming message is a response to one of our previous requests
                response_future = self._expected_responses[id]
                response_future.set_result(msg)
            else:
                # Incoming message is a request
                try:
                    response = await self.do_callback(msg)
                    if response:
                        await self.send_message(response)
                except Exception as exc:
                    logger.exception("Error during callback %s",  exc)
                    await self.send_error(msg.id, description=repr(exc))

    async def  do_callback(self, msg: pb.MessageV1) -> pb.MessageV1 | None:
        kind = get_message_kind(msg)

        try:
            field = pb.MessageV1.DESCRIPTOR.fields_by_name[kind]
        except KeyError:
            logger.warning("No message kind %s.", kind)
            return None


        if field.number not in self._callbacks:
            logger.warning("No callback registered for incoming message of type %s.", kind)
            return None

        callback, extra_args, extra_kwargs = self._callbacks[field.number]
        body = getattr(msg, kind)
        ret = await callback(body, *extra_args, **extra_kwargs)

        if ret is None:
            return None

        if isinstance(ret, pb.MessageV1):
            return ret

        return Protocol.new_message(ret, msg.id)
        #except KeyError as ex:
        #    logger.warning("No callback registered for incoming message of type %s.", message_type)
        #    pass

    #  ██████  ██████  ███    ███ ███    ███  █████  ███    ██ ██████  ███████
    # ██      ██    ██ ████  ████ ████  ████ ██   ██ ████   ██ ██   ██ ██
    # ██      ██    ██ ██ ████ ██ ██ ████ ██ ███████ ██ ██  ██ ██   ██ ███████
    # ██      ██    ██ ██  ██  ██ ██  ██  ██ ██   ██ ██  ██ ██ ██   ██      ██
    #  ██████  ██████  ██      ██ ██      ██ ██   ██ ██   ████ ██████  ███████

    async def get_entity(self) -> pb.Entity:
        response = await self.send_body_and_wait_response(pb.DescribeCommand())
        return response.describe_response.entity

    async def get_status(self, *, recursive: bool = True) -> dict:
        response = await self.send_body_and_wait_response(GetStatusRequest(recursive=recursive))
        return response.status

    async def get_system_temperatures(self) -> pb.TemperatureDataset:
        response = await self.send_body_and_wait_response(pb.ReadTemperatureCommand())
        return response.read_temperature_response.dataset

    async def get_config(self, path: Path | Entity, recursive: bool = True) -> pb.ConfigBundle:
        if isinstance(path, Entity):
            path = path.path

        response = await self.send_body_and_wait_response(
            pb.ExtractCommand(entity=pb.EntityId(path=str(path)), recursive=recursive))
        return response.extract_response.bundle

    async def set_config_request(self, configs: typing.List[pb.Config]) -> bool:
        return await self.send_body_and_wait_response(pb.ConfigCommand(bundle=pb.ConfigBundle(configs=configs)))

    async def set_config(self, entity: Entity):
        return await self.set_config_request(configs=build_config(entity))

    async def set_configs(self, entities: list[Entity]):
        for entity in entities:
            if not entity.path.depth == 1:
                raise NotImplementedError("Not yet implemented.")

        configs : typing.List[pb.Config] = []
        for entity in entities:
            configs.extend(build_config(entity))

        await self.set_config_request(configs=configs)

    async def set_daq_request(self, daq: DAQConfig, session: typing.Optional[uuid.UUID] = None):
        await self.send_body_and_wait_response(SetDAQRequest(daq=daq))

    async def set_standby(self, standby: bool, **kwargs):
        await self.send_body_and_wait_response(SetStandbyRequest(standby=standby, **kwargs))

    async def start_run_request(
        self,
        id_: uuid.UUID,
        run_config: RunConfig,
        daq_config: DAQConfig = None,
        sync_config: SyncConfig = None,
        calibration_config: CalibrationConfig = None,
        partition_config: PartitionConfig = None,
    ):

        pb_run_config = pb.RunConfig(
            ic_time=pb.Time(value=int(run_config.ic_time), prefix=pb.Prefix.NANO),
            op_time = pb.Time(value=int(run_config.op_time), prefix=pb.Prefix.NANO),
            halt_on_overload=run_config.halt_on_overload
        )

        pb_daq_config = pb.DaqConfig(
            num_channels=daq_config.num_channels,
            sample_rate = daq_config.sample_rate,
            sample_op = daq_config.sample_op,
            sample_op_end = daq_config.sample_op_end
        )

        pb_sync_config = pb.SyncConfig(
            enabled=sync_config.enabled,
            master = None if sync_config.master is None else pb.EntityId(path=str(sync_config.master)),
            group = sync_config.group
        )

        pb_calibration_config = pb.CalibrationConfig(
            enabled=calibration_config.enabled,
            leader=None if calibration_config.leader is None else pb.EntityId(path=str(calibration_config.leader))
        )

        current_time = time.perf_counter()
        await self.send_body_and_wait_response(pb.StartRunCommand(
            run_id=str(id_),
            run_config=pb_run_config,
            daq_config=pb_daq_config,
            sync_config=pb_sync_config,
            calibration_config=pb_calibration_config,
            # partition_config=partition_config,
            # session=None,
        ))

        final_time = time.perf_counter()
        roundtrip_time_pybrid_teensy_request = final_time - current_time
        logger.debug(f'roundtrip_time_pybrid_teensy_request: {roundtrip_time_pybrid_teensy_request} Sekunden')

    async def sys_reboot(self):
        logger.warning("System reboot is a matter of faith.")
        try:
            await self.send_body_and_wait_response(SysRebootRequest())
        except TimeoutError:
            # You will not receive a response, because controller restarts before sending it
            pass

    async def reset(self, keep_calibration: bool = True, sync: bool = True):
        await self.send_body_and_wait_response(pb.ResetCommand(keep_calibration=keep_calibration, sync=sync))

    async def reset_data_stream(self):
        if self.data_receiver is not None:
            self.data_transport.close()
            await self.data_receiver.stop()
            self.data_receiver = None
            self.data_transport = self.ctrl_transport

    async def udp_data_streaming(self, port: int):
        await self.reset_data_stream()

        self.data_transport = await UDPTransport.create(local_port=port)
        self.data_receiver = Receiver(self.data_transport, lambda msg: self.process(msg))
        await self.data_receiver.start()

        response = await self.send_body_and_wait_response(pb.UdpDataStreamingCommand(port=port))

        if get_message_kind(response) == "error_message":
            await self.reset_data_stream()
            return False

        return response

    async def udp_data_receiving(self, port: int):
        await self.reset_data_stream()
        self.data_transport = await UDPTransport.create(local_port=None, remote_host=str(self.remote_address), remote_port=port)
        return

    async def register_external_entities(self, entities: typing.Mapping[int, pb.Address]):
        # TODO: For large systems, we might not be able to send all items at once (limited JSON buffer size in firmware).
        #       In that case, split the request in multiple ones here, so other call sites don't have to do it themselves.
        await self.send_body_and_wait_response(pb.RegisterExternalEntitiesCommand(entities=entities))
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
from pybrid.base.transport import StreamTransport
from pybrid.redac.protocol.envelope import Envelope
from pybrid.redac.protocol.messages import (
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
from pybrid.redac.protocol.serializer import build_config
from pybrid.redac.entities import Path, Entity
from pybrid.redac.partitioning import PartitionConfig
from pybrid.redac.run import RunConfig, DAQConfig, CalibrationConfig
from pybrid.redac.sync import SyncConfig, SyncMode

from uuid import UUID, uuid4

from google.protobuf.json_format import MessageToJson
from google.protobuf.internal import encoder
from google.protobuf.internal import decoder
import pybrid.base.proto.main_pb2 as pb
from pybrid.base.transport.base import BaseTransport

logger = logging.getLogger(__name__)

def get_envelope_kind(msg: pb.Envelope) -> str | None :
    try:
        return msg.WhichOneof("kind")
    except:
        logger.warning("No message type present.")
        return None

class Receiver:
    def __init__(self, transport: BaseTransport, cb):
        self.transport = transport
        self.cb = cb
        self._receive_loop_task = None
        self._expected_responses: dict[UUID, asyncio.futures.Future] = dict()
        self._callbacks: dict[int, tuple[Callable, list, dict]] = dict()

    def __await__(self):
        return self._receive_loop_task.__await__()

    async def start(self):
        assert self._receive_loop_task is None
        self._receive_loop_task = asyncio.create_task(self._receive_loop())

    async def stop(self):
        assert self._receive_loop_task is not None
        self._receive_loop_task.cancel()
        try:
            await asyncio.gather(self._receive_loop_task, return_exceptions=False)
        except asyncio.exceptions.CancelledError:
            pass

    # ██████  ███████  ██████ ███████ ██ ██    ██ ██ ███    ██  ██████
    # ██   ██ ██      ██      ██      ██ ██    ██ ██ ████   ██ ██
    # ██████  █████   ██      █████   ██ ██    ██ ██ ██ ██  ██ ██   ███
    # ██   ██ ██      ██      ██      ██  ██  ██  ██ ██  ██ ██ ██    ██
    # ██   ██ ███████  ██████ ███████ ██   ████   ██ ██   ████  ██████

    async def _receive_loop(self):
        while True:
            try:
                if not await self._receive_message_and_process():
                    return False
            except EOFError:
                logger.info("Connection closed.")
                break
            except asyncio.TimeoutError:
                pass
            except asyncio.CancelledError:
                break
            except ConnectionError as exc:
                logger.info("Connection closed.")
                break
            except ProtocolError as exc:
                logger.exception("Error while receiving or processing envelope: %s.", exc)
            except Exception as exc:
                logger.exception("Unknown error: %s.", exc)


    async def _receive_message_and_process(self) -> bool:
        msg = await self._receive_message()
        if msg is None:
            return False
        await self.cb(msg)
        return True

    async def _receive_message(self) -> None | pb.MessageV1:
        data = await self.transport.receive_packet()
        if data is None:
            return None

        try:
            envelope = pb.Envelope.FromString(data)

            kind = get_envelope_kind(envelope)
            if kind != "message_v1":
                return None

            message = envelope.message_v1
            if message is None:
                return None
            if not message.HasField("run_data_message"):
                logger.debug("received: %s", MessageToJson(message))
            return message
        except:
            raise MalformedDataError(data)

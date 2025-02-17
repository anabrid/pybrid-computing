# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import asyncio
import json
import logging
import typing
import uuid
from typing import Callable

from packaging.version import Version

from pybrid.base.hybrid.protocol import (
    BaseProtocol,
    ProtocolError,
    MalformedDataError,
    UnsuccessfulRequestError,
)
from pybrid.base.transport import BaseTransport
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
)
from .serializer import build_config
from ..entities import Path, Entity
from ..partitioning import PartitionConfig
from ..run import RunConfig, DAQConfig
from ..sync import SyncConfig

logger = logging.getLogger(__name__)


class Protocol(BaseProtocol):

    def __init__(self, transport: BaseTransport, version: Version = None):
        super().__init__(transport, version)
        self._receive_loop_task = None
        self._expected_responses: dict[uuid, (Response, asyncio.futures.Future)] = dict()
        self._callbacks: dict[typing.Type[Message], tuple[Callable, list, dict]] = dict()

    async def start(self):
        assert self._receive_loop_task is None
        self._receive_loop_task = asyncio.create_task(self._receive_loop())

    async def stop(self):
        assert self._receive_loop_task is not None
        self._receive_loop_task.cancel()
        self.transport.close()
        try:
            await asyncio.gather(self._receive_loop_task, return_exceptions=False)
        except asyncio.exceptions.CancelledError:
            pass

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()

    def __await__(self):
        return self._receive_loop_task.__await__()

    # ███████ ███████ ███    ██ ██████  ██ ███    ██  ██████
    # ██      ██      ████   ██ ██   ██ ██ ████   ██ ██
    # ███████ █████   ██ ██  ██ ██   ██ ██ ██ ██  ██ ██   ███
    #      ██ ██      ██  ██ ██ ██   ██ ██ ██  ██ ██ ██    ██
    # ███████ ███████ ██   ████ ██████  ██ ██   ████  ██████

    async def send_envelope(self, envelope):
        data = envelope.json().encode("ascii")
        await self.transport.send_line(data)

    async def send_message_and_wait_response(self, message, timeout=3):
        response_fut = await self.send_message(message)
        await asyncio.wait_for(response_fut, timeout=timeout)
        return response_fut.result()

    async def send_message(self, message, envelope_id: typing.Optional[uuid.UUID] = None):
        # Generate an envelope
        envelope = Envelope.from_message(message, id_=envelope_id)
        # The response to this envelope is a future
        response_future = asyncio.get_event_loop().create_future()
        # A response is only expected for requests
        if isinstance(message, Request):
            self._expected_responses[envelope.id] = (
                message.get_expected_response_type(),
                response_future,
            )
        else:
            # But if the message is not a request, no response will ever come, just set result to None here
            response_future.set_result(None)

        await self.send_envelope(envelope)

        # Return future to response
        return response_future

    async def send_error(self, envelope_id: uuid.UUID, type_: str, error: str):
        envelope = Envelope(id=envelope_id, type=type_, msg=None, success=False, error=error)
        await self.send_envelope(envelope)

    # ██████  ███████  ██████ ███████ ██ ██    ██ ██ ███    ██  ██████
    # ██   ██ ██      ██      ██      ██ ██    ██ ██ ████   ██ ██
    # ██████  █████   ██      █████   ██ ██    ██ ██ ██ ██  ██ ██   ███
    # ██   ██ ██      ██      ██      ██  ██  ██  ██ ██  ██ ██ ██    ██
    # ██   ██ ███████  ██████ ███████ ██   ████   ██ ██   ████  ██████

    async def _receive_json(self) -> dict:
        data = await self.transport.receive_line()
        try:
            data_json = json.loads(data.decode("ascii"))
        except json.decoder.JSONDecodeError as exc:
            raise MalformedDataError(data) from exc
        else:
            return data_json

    async def _receive_message_and_process(self):
        data = await self._receive_json()
        envelope = Envelope(**data)

        if envelope.id is None:
            # Incoming message is a notification
            try:
                msg_class = Notification.get_class_for_type_identifier(envelope.type)
                notification = envelope.get_message(msg_class)
                response = await self.do_callback(notification)
            except Exception as exc:
                logger.exception("Error during callback for %s: %s", envelope.type, exc)
            else:
                if response is not None:
                    logger.warning("Return values of notification callback handlers are ignored.")

        elif envelope.id in self._expected_responses:
            # Incoming message is a response to one of our previous requests
            expected_response_type, response_future = self._expected_responses[envelope.id]
            if not envelope.success:
                response_future.set_exception(UnsuccessfulRequestError(envelope.error))
            else:
                try:
                    message = envelope.get_message(expected_response_type)
                except ProtocolError as exc:
                    response_future.set_exception(exc)
                else:
                    # TODO: Catch any exceptions
                    response_future.add_done_callback(
                        lambda future: asyncio.ensure_future(self.do_callback(future.result()))
                    )
                    response_future.set_result(message)

        else:
            # Incoming message is a request
            try:
                msg_class = Request.get_class_for_type_identifier(envelope.type)
                request = envelope.get_message(msg_class)
                response = await self.do_callback(request)
            except Exception as exc:
                logger.exception("Error during callback for %s: %s", envelope.type, exc)
                await self.send_error(envelope.id, envelope.type, repr(exc))
            else:
                if response:
                    await self.send_message(response, envelope_id=envelope.id)

    async def _receive_loop(self):
        while True:
            try:
                await self._receive_message_and_process()
            except asyncio.TimeoutError:
                pass
            except asyncio.CancelledError:
                break
            except ConnectionError as exc:
                logger.info("Connection %s closed.", self.transport.name)
                logger.warning("Remove this sleep :)")
                await asyncio.sleep(5)
                break
            except ProtocolError as exc:
                logger.exception("Error while receiving or processing envelope: %s.", exc)
            except Exception as exc:
                logger.exception("Unknown error: %s.", exc)

    #  ██████  █████  ██      ██      ██████   █████   ██████ ██   ██ ███████
    # ██      ██   ██ ██      ██      ██   ██ ██   ██ ██      ██  ██  ██
    # ██      ███████ ██      ██      ██████  ███████ ██      █████   ███████
    # ██      ██   ██ ██      ██      ██   ██ ██   ██ ██      ██  ██       ██
    #  ██████ ██   ██ ███████ ███████ ██████  ██   ██  ██████ ██   ██ ███████

    def register_callback(self, msg_type: typing.Type[Message], callback: Callable, extra_args=None, extra_kwargs=None):
        previous = self._callbacks.get(msg_type, None)
        self._callbacks[msg_type] = (callback, extra_args or list(), extra_kwargs or dict())
        return previous

    def get_callback(self, msg_type: typing.Type[Message]):
        return self._callbacks.get(msg_type, None)

    async def do_callback(self, msg: Message):
        try:
            callback, extra_args, extra_kwargs = self._callbacks[type(msg)]
        except KeyError:
            logger.warning("No callback registered for incoming message of type %s.", type(msg))
            pass
        else:
            return await callback(msg, *extra_args, **extra_kwargs)

    #  ██████  ██████  ███    ███ ███    ███  █████  ███    ██ ██████  ███████
    # ██      ██    ██ ████  ████ ████  ████ ██   ██ ████   ██ ██   ██ ██
    # ██      ██    ██ ██ ████ ██ ██ ████ ██ ███████ ██ ██  ██ ██   ██ ███████
    # ██      ██    ██ ██  ██  ██ ██  ██  ██ ██   ██ ██  ██ ██ ██   ██      ██
    #  ██████  ██████  ██      ██ ██      ██ ██   ██ ██   ████ ██████  ███████

    async def hack_request(self, cmd: str, data: typing.Any) -> typing.Any:
        response = await self.send_message_and_wait_response(HackRequest(command=cmd, data=data))
        return response.data

    async def get_entities(self) -> dict:
        response = await self.send_message_and_wait_response(GetEntitiesRequest())
        return response.entities

    async def get_status(self, *, recursive: bool = True) -> dict:
        response = await self.send_message_and_wait_response(GetStatusRequest(recursive=recursive))
        return response.status

    async def get_system_temperatures(self) -> dict:
        response = await self.send_message_and_wait_response(SysTemperaturesRequest())
        return response.entities

    async def get_config(self, entity: Path, recursive: bool = True) -> dict:
        response = await self.send_message_and_wait_response(GetCircuitRequest(entity=entity, recursive=recursive))
        return response.config

    async def set_config_request(self, entity: Path, config: dict, session: uuid.uuid4 = None) -> bool:
        await self.send_message_and_wait_response(SetCircuitRequest(entity=entity, config=config, session=session))
        return True

    async def set_config(self, entity: Entity):
        config = dict()
        build_config(entity, config)
        await self.set_config_request(entity=entity.path, config=config)
        return True

    async def set_configs(self, entities: list[Entity]):
        for entity in entities:
            if not entity.path.depth == 1:
                raise NotImplementedError("Not yet implemented.")
        config = {entity.path.id_: build_config(entity) for entity in entities}
        await self.set_config_request(entity=Path(), config=config)

    async def set_daq_request(self, daq: DAQConfig, session: typing.Optional[uuid.UUID] = None):
        await self.send_message_and_wait_response(SetDAQRequest(daq=daq))

    async def set_standby(self, standby: bool, **kwargs):
        await self.send_message_and_wait_response(SetStandbyRequest(standby=standby, **kwargs))

    async def start_run_request(
        self,
        id_: uuid.UUID,
        config: RunConfig,
        daq_config: DAQConfig = None,
        sync_config: SyncConfig = None,
        partition_config: PartitionConfig = None,
    ):
        await self.send_message_and_wait_response(
            StartRunRequest(
                id=id_,
                config=config,
                daq_config=daq_config,
                sync_config=sync_config,
                partition_config=partition_config,
                session=None,
            )
        )

    async def sys_reboot(self):
        logger.warning("System reboot is a matter of faith.")
        try:
            await self.send_message_and_wait_response(SysRebootRequest())
        except TimeoutError:
            # You will not receive a response, because controller restarts before sending it
            pass

    async def reset(self, keep_calibration: bool = True, sync: bool = True):
        await self.send_message_and_wait_response(ResetCircuitRequest(keep_calibration=keep_calibration, sync=sync))

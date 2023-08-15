# Copyright (c) 2022 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
#
# This file is part of the pyanabrid software packet.
#
# ANABRID_BEGIN_LICENSE:GPL
# Commercial License Usage
# Licensees holding valid commercial anabrid licenses may use this file in
# accordance with the commercial license agreement provided with the
# Software or, alternatively, in accordance with the terms contained in
# a written agreement between you and Anabrid GmbH. For licensing terms
# and conditions see https://www.anabrid.com/licensing. For further
# information use the contact form at https://www.anabrid.com/contact.
#
# GNU General Public License Usage
# Alternatively, this file may be used under the terms of the GNU
# General Public License version 3 as published by the Free Software
# Foundation and appearing in the file LICENSE.GPL3 included in the
# packaging of this file. Please review the following information to
# ensure the GNU General Public License version 3 requirements
# will be met: https://www.gnu.org/licenses/gpl-3.0.html.
# For Germany, additional rules exist. Please consult /LICENSE.DE
# for further agreements.
# ANABRID_END_LICENSE

import asyncio
import json
import logging
import uuid

from packaging.version import Version
from pyanabrid.base.hybrid.protocol import BaseProtocol, ProtocolError, MalformedDataError
from pyanabrid.base.transport import BaseTransport

from pyanabrid.redac.protocol.envelope import Envelope
from pyanabrid.redac.protocol.messages import Request, Response

logger = logging.getLogger(__name__)


class Protocol(BaseProtocol):

    def __init__(self, transport: BaseTransport, version: Version = None):
        super().__init__(transport, version)
        self._receive_loop_task = None
        self._expected_responses: dict[uuid, (Response, asyncio.futures)] = dict()

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

    # ███████ ███████ ███    ██ ██████  ██ ███    ██  ██████
    # ██      ██      ████   ██ ██   ██ ██ ████   ██ ██
    # ███████ █████   ██ ██  ██ ██   ██ ██ ██ ██  ██ ██   ███
    #      ██ ██      ██  ██ ██ ██   ██ ██ ██  ██ ██ ██    ██
    # ███████ ███████ ██   ████ ██████  ██ ██   ████  ██████

    async def send_message(self, message):
        envelope = Envelope.from_message(message)
        return await self.send_envelope(envelope)

    async def send_message_and_wait_response(self, message, timeout=3):
        response_fut = await self.send_message(message)
        await asyncio.wait_for(response_fut, timeout=timeout)
        return response_fut.result()

    async def send_envelope(self, envelope: Envelope):
        # The response to this envelope is a future
        response_future = asyncio.get_event_loop().create_future()
        # A response is only expected for requests
        if isinstance(envelope.msg, Request):
            self._expected_responses[envelope.id] = (envelope.msg.get_expected_response_type(), response_future)
        else:
            # But if the message is not a request, no response will ever come, just set result to None here
            response_future.set_result(None)

        # Send out data
        data = envelope.json().encode('ascii')
        await self.transport.send_line(data)

        # Return future to response
        return response_future

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
        envelope = Envelope.parse_obj(data)
        if envelope.id in self._expected_responses:
            expected_response_type, response_future = self._expected_responses[envelope.id]
            # TODO: Some error handling
            response_future.set_result(envelope.msg)

    async def _receive_loop(self):
        while True:
            try:
                await self._receive_message_and_process()
            except asyncio.CancelledError:
                break
            except asyncio.TimeoutError:
                pass
            except ProtocolError as exc:
                logger.exception(
                    "Error while receiving or processing envelope: %s.", exc
                )

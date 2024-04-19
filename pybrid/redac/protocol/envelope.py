# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import logging
import typing

from uuid import UUID, uuid4
from pydantic import BaseModel, Field, ValidationError

from pybrid.base.hybrid.protocol import MalformedDataError, MalformedMessageError

from .messages import Message

logger = logging.getLogger(__name__)


class MalformedEnvelopeError(MalformedDataError):
    pass


class Envelope(BaseModel):
    """
    Envelope containing a :class:`Message`.

    While the relevant data for the communication as part of this protocol is encoded
    using the various message classes, the most fundamental data package that is sent
    between two recipients is this envelope.

    The envelope contains an :attr:`id`, which is used to identify responses to previous requests
    (optional for notifications).

    The :attr:`type` field contains a unique type identifier, telling the recipient which :class:`Message`
    is contained in the :attr:`msg` field. The type identifier is defined to be the python message class name,
    with any Request, Response or Notification suffix removed and converted to underscore case.

    For responses, the :attr:`success` field and :attr:`error` field define whether the request was successfully
    handled. Only if :attr:`success` is true, :attr:`msg` contains an actual response.
    """
    #: Optional ID of the request and its response. None for Notifications
    id: typing.Optional[UUID] = Field(default_factory=uuid4)
    #: Unique string defining the type of the contained message
    type: str
    #: The msg, None if :attr:`success` is false for responses
    msg: typing.Optional[dict] = None
    #: Whether the request was handled successfully (only in responses)
    success: typing.Optional[bool] = Field(exclude=True, default=True)
    #: Optional error, in case :attr:`success` is false
    error: typing.Optional[str] = Field(exclude=True, default="")

    @classmethod
    def from_message(cls, message):
        return cls(**{"type": message.get_type_identifier(), "msg": message})

    def get_message(self) -> Message:
        try:
            msg_class = Message.get_class_for_type_identifier(self.type)
            msg = msg_class(**self.msg)
            return msg
        except (KeyError, AttributeError, ValidationError) as exc:
            logger.exception("Error while parsing message from envelope: %s.", exc)
            raise MalformedMessageError() from exc

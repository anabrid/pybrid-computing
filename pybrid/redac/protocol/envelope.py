# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import logging
import typing

from uuid import UUID, uuid4

from pydantic import BaseModel, Field, ValidationError

from pybrid.base.hybrid.protocol import MalformedDataError, MalformedMessageError, UnsuccessfulRequestError

from .messages import Message, Request, Response

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
    id: typing.Optional[UUID] = None
    #: Unique string defining the type of the contained message
    type: str
    #: The msg, None if :attr:`success` is false for responses
    msg: typing.Optional[dict] = None
    #: Whether the request was handled successfully (only in responses)
    success: typing.Optional[bool] = True
    #: Optional error, in case :attr:`success` is false
    error: typing.Optional[str] = ""

    @classmethod
    def from_message(cls, message, *, id_=None):
        kwargs = {"type": message.get_type_identifier(), "msg": message}
        if id_ is not None:
            kwargs["id"] = id_
        else:
            if isinstance(message, (Request, Response)):
                kwargs["id"] = uuid4()
        return cls(**kwargs)

    def get_message(self, msg_class=None) -> Message:
        if self.error:
            raise UnsuccessfulRequestError(self.error)
        try:
            msg_class = msg_class or Message.get_class_for_type_identifier(self.type)
            msg = msg_class(**self.msg)
            return msg
        except (KeyError, AttributeError, ValidationError) as exc:
            logger.exception("Error while parsing message from envelope: %s.", exc)
            raise MalformedMessageError() from exc

    def json(self, *args, **kwargs):
        if not self.success:
            exclude_ = {"msg"}
        else:
            exclude_ = {"success", "error"}
        kwargs.setdefault("exclude", exclude_)
        return super().json(*args, **kwargs)

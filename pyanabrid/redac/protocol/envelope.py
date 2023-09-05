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

import logging
import typing

from uuid import UUID, uuid4
from pydantic import BaseModel, Field, ValidationError

from pyanabrid.base.hybrid.protocol import MalformedDataError, MalformedMessageError

from .messages import Message

logger = logging.getLogger(__name__)


class MalformedEnvelopeError(MalformedDataError):
    pass


class Envelope(BaseModel):
    id: typing.Optional[UUID] = Field(default_factory=uuid4)
    type: str
    msg: typing.Optional[dict] = None
    success: typing.Optional[bool] = Field(exclude=True, default=True)
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

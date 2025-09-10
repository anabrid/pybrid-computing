# Copyright (c) 2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import typing

from pydantic import UUID4

from ..config import SimConfig
from ...redac.protocol.messages import Request, Response, SuccessInfo

class SetSimRequest(Request):
    """
    Request setting the configuration for a simulator, including, e.g.,
    plugins and k0.
    """

    #: The config with simulator-exclusive parameters.
    config: SimConfig
    #: The secret session ID for which the entities were reserved. Only required if session management is enabled.
    session: typing.Optional[UUID4]

class SetSimResponse(Response):
    """
    A response to a prior :class:`SetSimRequest`.
    """

    response_for = SetSimRequest

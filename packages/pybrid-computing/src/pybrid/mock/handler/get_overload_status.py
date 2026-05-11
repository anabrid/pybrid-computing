# Copyright (c) 2022-2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""Handler for the GetOverloadStatusCommand."""

import logging
from typing import TYPE_CHECKING

import pybrid.base.proto.main_pb2 as pb
from pybrid.mock.handler.base import BaseHandler

if TYPE_CHECKING:
    from pybrid.mock.connection import ClientConnection

logger = logging.getLogger(__name__)


class GetOverloadStatusHandler(BaseHandler):
    """Reports a "no overload" status for every request.

    The mock has no analog state, so there is nothing that could overload.
    """

    async def handle(
        self, cmd: pb.GetOverloadStatusCommand, connection: "ClientConnection"
    ) -> pb.GetOverloadStatusResponse:
        return pb.GetOverloadStatusResponse(
            status=pb.OverloadStatus(global_overload=False)
        )

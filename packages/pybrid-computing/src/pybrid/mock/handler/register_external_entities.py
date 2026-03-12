# Copyright (c) 2022-2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""Handler for the register external entities command."""

from typing import TYPE_CHECKING

import pybrid.base.proto.main_pb2 as pb
from pybrid.mock.handler.base import BaseHandler

if TYPE_CHECKING:
    from pybrid.mock.connection import ClientConnection


class RegisterExternalEntitiesHandler(BaseHandler):
    """Handler for external entities registration commands.

    Stores the received entity map for test inspection but performs no
    real coordination (DummyDAC doesn't route cross-carrier signals).
    """

    last_entities: dict[str, bytes]

    def __init__(self, server):
        super().__init__(server)
        self.last_entities = {}

    async def handle(
        self, cmd: pb.RegisterExternalEntitiesCommand, connection: "ClientConnection"
    ) -> pb.SuccessMessage:
        self.last_entities = {k: v.data for k, v in cmd.entities.items()}
        return pb.SuccessMessage()

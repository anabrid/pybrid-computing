# Copyright (c) 2022-2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""Handler for the register external entities command."""

from typing import TYPE_CHECKING

import pybrid.base.proto.main_pb2 as pb
from pybrid.mock.handler.base import BaseHandler

if TYPE_CHECKING:
    from pybrid.redac.protocol.protocol import Protocol


class RegisterExternalEntitiesHandler(BaseHandler):
    """
    Handler for external entities registration commands.

    This is a no-op for DummyDAC since it doesn't coordinate with external entities.
    """

    async def handle(
        self, cmd: pb.RegisterExternalEntitiesCommand, protocol: "Protocol"
    ) -> pb.SuccessMessage:
        """
        Handle external entities registration (no-op for DummyDAC).

        This command is sent by the Controller but doesn't need any action
        from the DummyDAC since it doesn't coordinate with external entities.

        :param cmd: The register external entities command.
        :param protocol: The protocol instance (unused).
        :return: SuccessMessage indicating the command was accepted.
        """
        return pb.SuccessMessage()

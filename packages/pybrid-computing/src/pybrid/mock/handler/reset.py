# Copyright (c) 2022-2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""Handler for the reset command."""

import logging
from typing import TYPE_CHECKING

import pybrid.base.proto.main_pb2 as pb
from pybrid.mock.handler.base import BaseHandler

if TYPE_CHECKING:
    from pybrid.mock.connection import ClientConnection

logger = logging.getLogger(__name__)


class ResetHandler(BaseHandler):
    """
    Handler for reset commands.

    Clears stored configuration state.
    """

    async def handle(self, cmd: pb.ResetCommand, connection: "ClientConnection") -> pb.ResetResponse:
        """
        Handle a reset command by clearing stored configuration.

        :param cmd: The reset command (unused but kept for future extension).
        :param connection: The client connection (unused but required by callback signature).
        :return: A ResetResponse indicating success.
        """
        logger.debug("RESET: Clearing stored configuration")
        self.server._stored_config = None
        if not cmd.keep_calibration:
            self.server._calibrated = False
            logger.debug("RESET: Calibration state cleared")
        logger.debug("RESET: Configuration cleared")
        return pb.ResetResponse()

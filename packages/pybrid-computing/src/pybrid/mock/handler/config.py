# Copyright (c) 2022-2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""Handler for the config command."""

import logging
from typing import TYPE_CHECKING, Union

import pybrid.base.proto.main_pb2 as pb
from pybrid.mock.config import DummyDACErrorStage
from pybrid.mock.handler.base import BaseHandler

if TYPE_CHECKING:
    from pybrid.mock.connection import ClientConnection

logger = logging.getLogger(__name__)


class ConfigHandler(BaseHandler):
    """
    Handler for config commands.

    Stores the configuration module and supports error injection
    at the AT_CONFIGURE stage.
    """

    async def handle(
        self, cmd: pb.ConfigCommand, connection: "ClientConnection"
    ) -> Union[pb.ConfigResponse, pb.ErrorMessage]:
        """
        Handle a config command by storing the configuration module.

        If error injection is configured at AT_CONFIGURE stage, returns an error
        instead of storing the configuration.

        :param cmd: The config command containing the module to store.
        :param connection: The client connection (unused but required by callback signature).
        :return: A ConfigResponse on success or ErrorMessage if error injection is active.
        """
        logger.debug(
            "CONFIG: Received module with %d items",
            len(cmd.module.items)
        )
        if self.server.config.error_stage == DummyDACErrorStage.AT_CONFIGURE:
            logger.debug("CONFIG: Error injection active (AT_CONFIGURE)")
            return pb.ErrorMessage(
                description=self.server.config.error_message or "Configuration error"
            )
        self.server._stored_config = cmd.module
        logger.debug("CONFIG: Stored %d configurations", len(cmd.module.items))
        return pb.ConfigResponse()

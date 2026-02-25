# Copyright (c) 2022-2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""Handler for the describe command."""

import logging
from typing import TYPE_CHECKING

import pybrid.base.proto.main_pb2 as pb
from pybrid.mock.handler.base import BaseHandler

if TYPE_CHECKING:
    from pybrid.mock.connection import ClientConnection

logger = logging.getLogger(__name__)


class DescribeHandler(BaseHandler):
    """
    Handler for describe commands.

    Returns the entity tree representing the DummyDAC's hardware topology.
    """

    async def handle(
        self, cmd: pb.DescribeCommand, connection: "ClientConnection"
    ) -> pb.DescribeResponse:
        """
        Handle a describe command by returning the entity tree.

        :param cmd: The describe command (unused but required by interface).
        :param connection: The client connection (unused but required by callback signature).
        :return: A DescribeResponse containing the entity tree.
        """
        logger.debug(
            "DESCRIBE: Building entity tree with %d carriers",
            len(self.server._carrier_macs)
        )
        entity = self.server._build_entity_tree()
        logger.debug(
            "DESCRIBE: Returning entity tree with %d carrier children",
            len(entity.children)
        )
        return pb.DescribeResponse(entity=entity)

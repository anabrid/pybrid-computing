# Copyright (c) 2022-2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""Handler for the extract command."""

import logging
from typing import TYPE_CHECKING, Union

import pybrid.base.proto.main_pb2 as pb
from pybrid.mock.config import DummyDACErrorStage
from pybrid.mock.handler.base import BaseHandler

if TYPE_CHECKING:
    from pybrid.mock.connection import ClientConnection

logger = logging.getLogger(__name__)


class ExtractHandler(BaseHandler):
    """
    Handler for extract commands.

    Returns configurations filtered by entity path prefix and supports
    error injection at the AT_EXTRACT stage.
    """

    async def handle(
        self, cmd: pb.ExtractCommand, connection: "ClientConnection"
    ) -> Union[pb.ExtractResponse, pb.ErrorMessage]:
        """
        Handle an extract command by returning filtered configurations.

        Returns configurations that match the requested entity path prefix.
        If error injection is configured at AT_EXTRACT stage, returns an error.

        :param cmd: The extract command specifying the entity path to filter by.
        :param connection: The client connection (unused but required by callback signature).
        :return: An ExtractResponse with matching configs or ErrorMessage if error injection is active.
        """
        logger.debug(
            "EXTRACT: Request for path '%s' (recursive=%s)",
            cmd.entity.path,
            cmd.recursive
        )
        if self.server.config.error_stage == DummyDACErrorStage.AT_EXTRACT:
            logger.debug("EXTRACT: Error injection active (AT_EXTRACT)")
            return pb.ErrorMessage(
                description=self.server.config.error_message or "Extract error"
            )
        matching_configs = self._filter_configs_by_path(cmd.entity.path)
        logger.debug("EXTRACT: Found %d matching configs", len(matching_configs))
        return pb.ExtractResponse(bundle=pb.ConfigBundle(configs=matching_configs))

    def _filter_configs_by_path(self, path: str) -> list:
        """
        Filter stored configurations by entity path prefix.

        Handles path normalization - both paths with and without leading slashes
        are matched correctly.

        :param path: The path prefix to filter by.
        :return: List of configs whose entity paths start with the given prefix.
        """
        if self.server._stored_config is None:
            return []

        # Normalize the filter path (add leading slash if missing)
        normalized_path = path if path.startswith('/') else f'/{path}'

        return [
            c for c in self.server._stored_config.configs
            if c.entity.path.startswith(normalized_path)
        ]

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
    """Handler for extract commands.

    Returns entity specifications and/or operational configurations
    filtered by entity path prefix. Supports error injection at the
    AT_EXTRACT stage.
    """

    async def handle(
        self, cmd: pb.ExtractCommand, connection: "ClientConnection"
    ) -> Union[pb.ExtractResponse, pb.ErrorMessage]:
        logger.debug(
            "EXTRACT: path='%s' recursive=%s specification=%s configuration=%s",
            cmd.entity.path if cmd.HasField("entity") else "<none>",
            cmd.recursive,
            cmd.specification,
            cmd.configuration,
        )
        if self.server.config.error_stage == DummyDACErrorStage.AT_EXTRACT:
            logger.debug("EXTRACT: Error injection active (AT_EXTRACT)")
            return pb.ErrorMessage(
                description=self.server.config.error_message or "Extract error"
            )

        items: list[pb.Item] = []

        if cmd.specification:
            entity_tree = self.server._build_entity_tree()
            spec_item = pb.Item(
                entity_specification=pb.EntitySpecification(entity=entity_tree)
            )
            items.append(spec_item)

        if cmd.configuration:
            items.extend(self._filter_configs_by_path(
                cmd.entity.path if cmd.HasField("entity") else ""
            ))

        logger.debug("EXTRACT: Returning %d items", len(items))
        return pb.ExtractResponse(module=pb.Module(items=items))

    def _filter_configs_by_path(self, path: str) -> list[pb.Item]:
        """Filter stored configuration items by entity path prefix."""
        if self.server._stored_config is None:
            return []

        if not path:
            return list(self.server._stored_config.items)

        normalized_path = path if path.startswith('/') else f'/{path}'

        return [
            c for c in self.server._stored_config.items
            if c.entity.path.startswith(normalized_path)
        ]

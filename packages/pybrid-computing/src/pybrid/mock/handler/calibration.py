# Copyright (c) 2022-2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""Handler for the calibration command."""

import logging
from typing import TYPE_CHECKING, Union

import pybrid.base.proto.main_pb2 as pb
from pybrid.mock.handler.base import BaseHandler

if TYPE_CHECKING:
    from pybrid.mock.connection import ClientConnection

logger = logging.getLogger(__name__)


class CalibrationHandler(BaseHandler):
    """Handler for calibration commands.

    Sets the server's calibration flag so that subsequent runs produce
    calibration-adjusted sample data.
    """

    async def handle(
        self, cmd: pb.CalibrationCommand, connection: "ClientConnection"
    ) -> Union[pb.CalibrationResponse, pb.ErrorMessage]:
        cfg = cmd.config
        any_enabled = (
            cfg.math == pb.CalibrationConfig.Enabled
            or cfg.gain == pb.CalibrationConfig.Enabled
            or cfg.offset == pb.CalibrationConfig.Enabled
        )
        self.server._calibrated = any_enabled
        logger.debug(
            "CALIBRATE: calibrated=%s (math=%s, gain=%s, offset=%s, leader=%s)",
            any_enabled,
            pb.CalibrationConfig.Kind.Name(cfg.math),
            pb.CalibrationConfig.Kind.Name(cfg.gain),
            pb.CalibrationConfig.Kind.Name(cfg.offset),
            cfg.leader.path if cfg.HasField("leader") else "<none>",
        )
        return pb.CalibrationResponse()

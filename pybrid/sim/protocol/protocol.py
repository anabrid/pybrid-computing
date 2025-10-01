# Copyright (c) 2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import logging

from pybrid.sim.config import SimConfig
from pybrid.redac.protocol.protocol import Protocol as REDACProtocol
import pybrid.base.proto.main_pb2 as pb

logger = logging.getLogger(__name__)

class Protocol(REDACProtocol):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    async def set_sim_config(self, sim_config: SimConfig):
        # convert to protobuf message
        new_msg = pb.SimConfigCommand(
            with_limits=sim_config.with_limits,
            k0=sim_config.k0,
            only_module_sinks=sim_config.only_module_sinks
        )

        if sim_config.acl_config:
            plugins = [
                pb.ACLPlugin(
                    plugin=obj.plugin,
                    label=obj.label,
                    parameters=obj.parameters
                ) for obj in sim_config.acl_config.plugins
            ]
            inputs = [
                pb.ACLBind(
                    acl=obj.acl,
                    plugin=obj.plugin,
                    pin=obj.pin
                ) for obj in sim_config.acl_config.inputs
            ]
            outputs = [
                pb.ACLBind(
                    acl=obj.acl,
                    plugin=obj.plugin,
                    pin=obj.pin
                ) for obj in sim_config.acl_config.outputs
            ]
            new_msg.acl_config = pb.ACLConfig(
                plugins=plugins,
                inputs=inputs,
                outputs=outputs
            )

        response = await self.send_body_and_wait_response(new_msg)
  
# Copyright (c) 2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import logging

import pybrid.base.proto.main_pb2 as pb
from pybrid.redac.protocol.protocol import Protocol as REDACProtocol
from pybrid.sim.config import SimConfig

logger = logging.getLogger(__name__)

class Protocol(REDACProtocol):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    async def set_sim_config(self, sim_config: SimConfig):
        # convert to protobuf message
        acl_config = None
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
            acl_config = pb.ACLConfig(
                plugins=plugins,
                inputs=inputs,
                outputs=outputs
            )

        new_msg = pb.SimConfigCommand(
            with_limits=sim_config.with_limits,
            k0=sim_config.k0,
            only_module_sinks=sim_config.only_module_sinks,
            acl_config=acl_config
        )

        return await self.send_body_and_wait_response(new_msg)
  
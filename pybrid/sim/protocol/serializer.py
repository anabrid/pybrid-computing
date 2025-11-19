# Copyright (c) 2022-2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later
from pybrid.base.hybrid.serializer import ConfigCollector, to_pb
from pybrid.redac.entities import Entity, Path
from pybrid.sim.computer import SimConfigEntity

from pybrid.base.proto import main_pb2 as pb

@to_pb.register
def _(sim_config: SimConfigEntity, collector: ConfigCollector):

    # always add sim_config to root entity as a "global" value
    pb_sim_config = collector.new_config(Entity(Path())).sim_config

    # add plugins
    if sim_config.k0:
        pb_sim_config.k0 = sim_config.k0
    pb_sim_config.with_limits = sim_config.with_limits
    pb_sim_config.only_module_sinks = sim_config.only_module_sinks

    # convert plug-based notation to more general wiring notation
    acl_config = None
    if sim_config.acl_config:
        plugins = [
            pb.ACLPlugin(
                plugin=obj.plugin,
                label=obj.label,
                parameters=obj.parameters
            ) for obj in sim_config.acl_config.plugins
        ]

        # note: the outward pybrid notation currently supports
        # ACL selects only in the first (and only) carrier in a LUCIDAC
        # so we will assume this here as well
        wires = []

        # inputs: plugin to device
        for obj in sim_config.acl_config.inputs:
            plug_plugin = pb.ACLPlug(
                kind=pb.ACLPlug.Kind.Plugin,
                entity_id=pb.EntityId(f"plugins/{obj.pin}/{obj.pin}")
            )
            plug_device = pb.ACLPlug(
                kind=pb.ACLPlug.Kind.Device,
                entity_id=pb.EntityId(f"00-00-00-00-00-00/0/{24 + obj.acl}")
            )
            wires.append(pb.ACLWire(lhs=plug_plugin, rhs=plug_device))
        
        # outputs: device to plugin
        for obj in sim_config.acl_config.outputs:
            plug_device = pb.ACLPlug(
                kind=pb.ACLPlug.Kind.Device,
                entity_id=pb.EntityId(f"00-00-00-00-00-00/0/{24 + obj.acl}")
            )
            plug_plugin = pb.ACLPlug(
                kind=pb.ACLPlug.Kind.Plugin,
                entity_id=pb.EntityId(f"plugins/{obj.pin}/{obj.pin}")
            )
            wires.append(pb.ACLWire(lhs=plug_plugin, rhs=plug_plugin))

        pb_sim_config.acl_config = pb.ACLConfig(
            plugins=plugins,
            wires=wires
        )


# Copyright (c) 2022-2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

from functools import singledispatchmethod
from typing import TYPE_CHECKING

from pybrid.base.proto import main_pb2 as pb
from pybrid.redac.carrier import ADCChannel, Carrier
from pybrid.redac.entities import Entity, Path
from pybrid.redac.protocol.serializer import REDACDeserializer, REDACSerializer
from pybrid.sim.computer import SimConfigEntity

if TYPE_CHECKING:
    from pybrid.sim.computer import Simulator


class SimulatorSerializer(REDACSerializer):
    """
    See :class:`REDACSerializer`.
    """

    def __init__(self):
        super().__init__()

    @singledispatchmethod
    def _serialize_configuration(self, entity: Entity):
        return super()._serialize_configuration(entity)

    @_serialize_configuration.register
    def _(self, sim_config: SimConfigEntity):

        # always add sim_config to root entity as a "global" value
        pb_sim_config = self.cc.new_config(Entity(Path())).sim_config

        # add plugins
        if sim_config.k0:
            pb_sim_config.k0 = sim_config.k0
        pb_sim_config.with_limits = sim_config.with_limits
        pb_sim_config.only_module_sinks = sim_config.only_module_sinks

        # convert plug-based notation to more general wiring notation
        if sim_config.acl_config:
            plugins = [
                pb.ACLPlugin(plugin=obj.plugin, label=obj.label, parameters=obj.parameters)
                for obj in sim_config.acl_config.plugins
            ]

            # note: the outward pybrid notation currently supports
            # ACL selects only in the first (and only) carrier in a LUCIDAC
            # so we will assume this here as well
            wires = []

            # inputs: plugin to device
            for obj in sim_config.acl_config.inputs:
                plug_plugin = pb.ACLPlug(
                    kind=pb.ACLPlug.Kind.Plugin, entity_id=pb.EntityId(path=f"plugins/{obj.plugin}/{obj.pin}")
                )
                plug_device = pb.ACLPlug(
                    kind=pb.ACLPlug.Kind.Device, entity_id=pb.EntityId(path=f"00-00-00-00-00-00/0/{24 + obj.acl}")
                )
                wires.append(pb.ACLWire(source=plug_plugin, target=plug_device))

            # outputs: device to plugin
            for obj in sim_config.acl_config.outputs:
                plug_device = pb.ACLPlug(
                    kind=pb.ACLPlug.Kind.Device, entity_id=pb.EntityId(path=f"00-00-00-00-00-00/0/{24 + obj.acl}")
                )
                plug_plugin = pb.ACLPlug(
                    kind=pb.ACLPlug.Kind.Plugin, entity_id=pb.EntityId(path=f"plugins/{obj.plugin}/{obj.pin}")
                )
                wires.append(pb.ACLWire(source=plug_device, target=plug_plugin))

            acl_config = pb.ACLConfig(plugins=plugins, wires=wires)
            pb_sim_config.acl_config.CopyFrom(acl_config)


class SimulatorDeserializer(REDACDeserializer):
    """
    See :class:`REDACDeserializer`.
    """

    def __init__(self, computer: "Simulator"):
        super().__init__(computer)

    @singledispatchmethod
    def _deserialize_configuration(self, config):
        return super()._deserialize_configuration(config)

    @_deserialize_configuration.register
    def _(self, config: pb.SimConfig):
        """Deserialize simulator configuration and apply to SimConfigEntity."""
        from pybrid.sim.config import ACLBind, ACLConfig, ACLPlugin

        entity_path = Path.parse(self._current_full_config.entity.path)
        entity = self.computer.get_entity(entity_path)

        # Deserialize basic simulation settings
        entity.with_limits = config.with_limits
        entity.only_module_sinks = config.only_module_sinks

        # Deserialize ACL configuration if present
        if config.HasField("acl_config"):
            pb_acl_config = config.acl_config

            # Deserialize plugins
            plugins = [
                ACLPlugin(plugin=pb_plugin.plugin, label=pb_plugin.label, parameters=list(pb_plugin.parameters))
                for pb_plugin in pb_acl_config.plugins
            ]

            # Convert wires back to inputs/outputs notation
            inputs = []
            outputs = []

            for wire in pb_acl_config.wires:
                # Check wire direction based on source and target kinds
                source_kind = wire.source.kind if wire.HasField("source") else None
                target_kind = wire.target.kind if wire.HasField("target") else None

                if source_kind == pb.ACLPlug.Kind.Plugin and target_kind == pb.ACLPlug.Kind.Device:
                    # Plugin to device = input to circuit
                    # Parse entity_id to extract pin and acl
                    # Format: "plugins/{plugin name}/{pin}" and "00-00-00-00-00-00/0/{24 + acl}"
                    source_id_parts = wire.source.entity_id.path.split("/")
                    target_id_parts = wire.target.entity_id.path.split("/")

                    if len(source_id_parts) >= 3 and len(target_id_parts) >= 3:
                        pin = int(source_id_parts[2])
                        acl = int(target_id_parts[2]) - 24

                        # Find plugin name by matching label
                        plugin_name = None
                        for pb_plugin in pb_acl_config.plugins:
                            if pb_plugin.label == source_id_parts[1]:
                                plugin_name = pb_plugin.label
                                break

                        if plugin_name:
                            inputs.append(ACLBind(acl=acl, plugin=plugin_name, pin=pin))
                        else:
                            raise Exception(f"Plugin from path {wire.source.entity_id.path} not found!")

                    else:
                        raise Exception("Invalid path found in wire format!")

                elif source_kind == pb.ACLPlug.Kind.Device and target_kind == pb.ACLPlug.Kind.Plugin:
                    # Device to plugin = output from circuit
                    source_id_parts = wire.source.entity_id.path.split("/")
                    target_id_parts = wire.target.entity_id.path.split("/")

                    if len(source_id_parts) >= 3 and len(target_id_parts) >= 3:
                        acl = int(source_id_parts[2]) - 24
                        pin = int(target_id_parts[2])

                        # Find plugin name by matching label
                        plugin_name = None
                        for pb_plugin in pb_acl_config.plugins:
                            if pb_plugin.label == target_id_parts[1]:
                                plugin_name = pb_plugin.label
                                break

                        if plugin_name:
                            outputs.append(ACLBind(acl=acl, plugin=plugin_name, pin=pin))
                        else:
                            raise Exception(f"Plugin from path {wire.source.entity_id.path} not found!")

                    else:
                        raise Exception("Invalid path found in wire format!")

                else:
                    raise Exception("DEVICE <> DEVICE connections are not supported by the simulator.")

            entity.acl_config = ACLConfig(plugins=plugins, inputs=inputs, outputs=outputs)

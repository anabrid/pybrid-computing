# Copyright (c) 2022-2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

from functools import singledispatchmethod

from pybrid.redac.protocol.serializer import REDACSerializer, REDACDeserializer
from pybrid.lucidac.front_plane import FrontPlane, SignalGenerator
from pybrid.redac.entities import Entity, Loc, Path
from pybrid.redac.carrier import Carrier
from pybrid.base.proto import main_pb2 as pb


class LUCIDACSerializer(REDACSerializer):

    def __init__(self):
        super().__init__()

    @singledispatchmethod
    def _serialize_specification(self, entity: Entity) -> pb.Entity:
        return super()._serialize_specification(entity)

    @_serialize_specification.register
    def _(self, entity: FrontPlane) -> pb.Entity:
        """Serialize a FrontPlane as a FRONTPANEL-class pb.Entity leaf node."""
        from pybrid.redac.entities import EntityType
        et = getattr(entity, "entity_type", None)
        if et is None:
            et = EntityType.reverse_lookup(FrontPlane)
        version = self._make_version(et.version)
        return pb.Entity(
            id=self._entity_id(entity),
            class_=et.class_.value,
            type=et.type_ or 0,
            variant=et.variant or 0,
            version=version,
        )

    @singledispatchmethod
    def _serialize_configuration(self, entity: Entity):
        return super()._serialize_configuration(entity)

    @_serialize_configuration.register
    def _(self, entity: FrontPlane):
        fp_config = self.cc.new_config(entity).front_panel_config
        fp_config.leds = entity.leds

        sg_config = self.cc.new_config(entity).signal_generator_config
        sg_config.frequency = entity.signal_generator.frequency
        sg_config.phase = entity.signal_generator.phase
        sg_config.wave_form = entity.signal_generator.wave_form
        sg_config.amplitude = entity.signal_generator.amplitude
        sg_config.square_voltage_low = entity.signal_generator.square_voltage_low
        sg_config.square_voltage_high = entity.signal_generator.square_voltage_high
        sg_config.offset = entity.signal_generator.offset
        sg_config.sleep = entity.signal_generator.sleep

        for val in entity.signal_generator.dac_outputs:
            sg_config.dac_outputs.append(val)


class LUCIDACDeserializer(REDACDeserializer):

    def __init__(self, computer=None):
        super().__init__(computer)
        self._carrier_counter = 0

    def _spec_carrier(self, entity: pb.Entity, path: Path, location: Loc = None) -> Carrier:
        if location is None and not entity.HasField("location_v0"):
            location = Loc.new_carrier(0, self._carrier_counter)
            self._carrier_counter += 1
        return super()._spec_carrier(entity, path, location)

    def _handle_unknown_carrier_child(self, path: Path, child: pb.Entity):
        """Detect FrontPlane by path name, since firmware reports class_=UNKNOWN(0)."""
        if path.id_ == "FP":
            front_plane = FrontPlane(path)
            acl_select = 8 * ["INTERNAL"]
            return (front_plane, acl_select)
        return super()._handle_unknown_carrier_child(path, child)

    @singledispatchmethod
    def _deserialize_configuration(self, config):
        return super()._deserialize_configuration(config)

    @_deserialize_configuration.register
    def _(self, config: pb.FrontPanelConfig):
        """Deserialize front panel LED configuration and apply to FrontPanel."""
        entity_path = Path.parse(self._current_full_config.entity.path)
        entity = self.computer.get_entity(entity_path)
        entity.leds = config.leds

    @_deserialize_configuration.register
    def _(self, config: pb.SignalGeneratorConfig):
        """Deserialize signal generator configuration and apply to FrontPanel."""
        entity_path = Path.parse(self._current_full_config.entity.path)
        entity = self.computer.get_entity(entity_path)

        entity.signal_generator = SignalGenerator(
            frequency=config.frequency,
            phase=config.phase,
            wave_form=config.wave_form,
            amplitude=config.amplitude,
            square_voltage_low=config.square_voltage_low,
            square_voltage_high=config.square_voltage_high,
            offset=config.offset,
            sleep=config.sleep,
            dac_outputs=list(config.dac_outputs)
        )



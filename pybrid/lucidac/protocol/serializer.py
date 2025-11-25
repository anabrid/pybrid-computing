# Copyright (c) 2022-2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

from pybrid.base.hybrid.serializer import Serializer
from pybrid.redac.protocol.serializer import REDACSerializer, REDACDeserializer
from pybrid.lucidac.front_panel import FrontPanel, SignalGenerator
from pybrid.redac.entities import Entity, Path
from pybrid.base.proto import main_pb2 as pb

class LUCIDACSerializer(REDACSerializer):

    def __init__(self):
        super().__init__()

    @REDACSerializer._serialize.register
    def _(self, entity: FrontPanel):
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

    def __init__(self, computer):
        super().__init__(computer)

    @REDACDeserializer._deserialize.register
    def _(self, entity, config: pb.FrontPanelConfig):
        """Deserialize front panel LED configuration and apply to FrontPanel."""
        entity.leds = config.leds

    @REDACDeserializer._deserialize.register
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
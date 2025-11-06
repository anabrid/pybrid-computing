# Copyright (c) 2022-2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later
from pybrid.base.hybrid.serializer import ConfigCollector, to_pb
from pybrid.lucidac.front_panel import FrontPanel

@to_pb.register
def to_pb(entity: FrontPanel, collector: ConfigCollector):
    fp_config = collector.new_config(entity).front_panel_config
    fp_config.leds = entity.leds

    sg_config = collector.new_config(entity).signal_generator_config
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
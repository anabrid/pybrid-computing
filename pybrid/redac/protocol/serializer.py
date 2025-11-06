# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later
from functools import singledispatch

from pybrid.base.proto import main_pb2 as pb
from pybrid.redac.blocks import CBlock, MMulBlock, TBlock, MIntBlock, UBlock, IBlock
from pybrid.redac.carrier import Carrier
from pybrid.redac.elements import ComputationElement

from pybrid.base.hybrid.serializer import ConfigCollector, to_pb

@to_pb.register
def _(entity: ComputationElement, collector: ConfigCollector):
    return None

@to_pb.register
def _(entity: Carrier, collector: ConfigCollector):
    adc_config = collector.new_config(entity).adc_config
    adc_channels = adc_config.channels

    for adc_channel in entity.adc_channels:
        if adc_channel is not None:
            pb_adc_channel = adc_channels.add()
            pb_adc_channel.idx = adc_channel

    if len(adc_config.channels) == 0:
        collector.pop_config()

    if entity.acl_select:
        acl_config = collector.new_config(entity).port_config
        acl_select = acl_config.states

        for interface in entity.acl_select:
            acl_select.append(pb.PortConfig.AclState.EXTERNAL if \
                interface == "external" else pb.PortConfig.AclState.INTERNAL)

@to_pb.register
def _(entity: CBlock, collector: ConfigCollector):
    coef_config = collector.new_config(entity).coef_config
    elements = coef_config.elements
    for elem_idx, element in enumerate(entity.elements):
        elements.append(pb.CoefConfig.Element(idx=elem_idx,factor=element.computation.factor))

@to_pb.register
def _(entity: MMulBlock, collector: ConfigCollector):
    pass
    #mul_config = collector.new_config(entity).mul_config

@to_pb.register
def _(entity: MIntBlock, collector: ConfigCollector):
    itor_config = collector.new_config(entity).itor_config
    for elem_idx, element in enumerate(entity.elements):
        pb_element = itor_config.elements.add()
        pb_element.idx = elem_idx
        pb_element.ic = element.ic
        pb_element.k = int(element.k)

    config = collector.new_config(entity)
    limiter_config = config.limiter_config
    for idx, bit in enumerate(entity.limiters):
        limiter_config.elements.append(pb.LimiterConfig.Element(idx=idx, enable=bit))

@to_pb.register
def _(entity: IBlock, collector: ConfigCollector):
    sum_config = collector.new_config(entity).sum_config
    for sum_idx, inputs in enumerate(entity.outputs):
        if len(inputs) == 0:
            continue
        sum_config.connections.append(pb.SumConnectionConfig(inputs=inputs, output=sum_idx))

    if len(sum_config.connections) == 0:
        collector.pop_config()
        return

    for lane_idx, bit in enumerate(entity.upscaling):
        sum_config.upscales.append(pb.UpscaleConfig(lane=lane_idx, enabled=bit))

@to_pb.register
def _(entity: UBlock, collector: ConfigCollector):
    select_config = collector.new_config(entity).select_config
    if not entity.constant:
        select_config.constant = pb.SelectConfig.ConstantConfig.GROUND
    else:
        constant = 1.0 if entity.constant == True else entity.constant
        select_config.constant = pb.SelectConfig.ConstantConfig.POS_REF if constant > 0 else pb.SelectConfig.ConstantConfig.NEG_REF
        select_config.magnitude = pb.SelectConfig.Magnitude.ONE if constant == 1.0 else pb.SelectConfig.Magnitude.ONE_TENTH

    for output, input in enumerate(entity.outputs):
        if input is None:
            continue
        select_config.connections.append(pb.SelectConnectionConfig(input=input, output=output))

    if len(select_config.connections) == 0:
        collector.pop_config()
    else:
        pass

@to_pb.register
def _(entity: TBlock, collector: ConfigCollector):
    switch_config = collector.new_config(entity).switch_config
    for idx, state in enumerate(entity.muxes):
        if idx is None:
            continue
        switch_config.muxes.append(pb.Mux(state=state))

    if len(switch_config.muxes) == 0:
        collector.pop_config()

    use_config = collector.new_config(entity).use_config
    for idx, (uses, source, target_upscaled) in enumerate(zip(entity.uses, entity.sources, entity.targets_upscaled)):
        if source is None:
            continue
        use_config.uses.extend([pb.Use(idx=idx, count=uses, source=source, upscaled=target_upscaled) ])

    if len(use_config.uses) == 0:
        collector.pop_config()

# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later
import queue

from functools import singledispatch
from typing import List, Any, Dict

from ...base.hybrid.computer import AnalogComputer
from pybrid.base.hybrid.entities import Entity
from pybrid.base.proto import main_pb2 as pb
from pybrid.redac.blocks import CBlock, MMulBlock, TBlock, MIntBlock, UBlock, IBlock
from pybrid.redac.carrier import Carrier, ADCChannel
from pybrid.redac.elements import ComputationElement
from pybrid.redac.entities import Path

from pybrid.base.hybrid.serializer import Serializer, Deserializer

_CONFIG_TYPE = Dict[str, Any] | List[pb.Config]

class REDACSerializer(Serializer):

    def __init__(self):
        super().__init__()

    def config_type(self) -> type:
        return List[pb.Config]
    
    def serialize(self, computer: AnalogComputer) -> _CONFIG_TYPE:
        return self.serialize_entities(computer.get_config_entities())
    
    def serialize_entities(self, entities: List[Entity]) -> _CONFIG_TYPE:
        """
        Serializes the configuration of a single entity.
        """
        configs = []
        self.cc = Serializer.ConfigCollector(configs)

        # recursively traverse over all top-level entities
        for entity in entities:
            traversal = queue.Queue()
            traversal.put(entity)
            while not traversal.empty():
                entity = traversal.get()
                for child in entity.children:
                    traversal.put(child)
                self._serialize(entity)

        return configs

    @Serializer._serialize.register
    def _(self, entity: ComputationElement):
        return None

    @Serializer._serialize.register
    def _(self, entity: Carrier):
        adc_config = self.cc.new_config(entity).adc_config
        adc_channels = adc_config.channels

        for adc_channel in entity.adc_config:
            if adc_channel is not None:
                pb_adc_channel = adc_channels.add()
                pb_adc_channel.idx = adc_channel.index
                pb_adc_channel.gain = adc_channel.gain
                pb_adc_channel.offset = adc_channel.offset

        if len(adc_config.channels) == 0:
            self.cc.pop_config()

        if entity.acl_select:
            acl_config = self.cc.new_config(entity).port_config
            acl_select = acl_config.states

            for interface in entity.acl_select:
                acl_select.append(pb.PortConfig.AclState.EXTERNAL if \
                    interface == "external" else pb.PortConfig.AclState.INTERNAL)

    @Serializer._serialize.register
    def _(self, entity: CBlock):
        coef_config = self.cc.new_config(entity).coef_config
        elements = coef_config.elements
        for elem_idx, element in enumerate(entity.elements):
            elements.append(pb.CoefConfig.Element(idx=elem_idx,factor=element.computation.factor))

    @Serializer._serialize.register
    def _(self, entity: MMulBlock):
        pass
        #mul_config = self.cc.new_config(entity).mul_config

    @Serializer._serialize.register
    def _(self, entity: MIntBlock):
        itor_config = self.cc.new_config(entity).itor_config
        for elem_idx, element in enumerate(entity.elements):
            pb_element = itor_config.elements.add()
            pb_element.idx = elem_idx
            pb_element.ic = element.ic
            pb_element.k = int(element.k)

        config = self.cc.new_config(entity)
        limiter_config = config.limiter_config
        for idx, bit in enumerate(entity.limiters):
            limiter_config.elements.append(pb.LimiterConfig.Element(idx=idx, enable=bit))

    @Serializer._serialize.register
    def _(self, entity: IBlock):
        sum_config = self.cc.new_config(entity).sum_config
        for sum_idx, inputs in enumerate(entity.outputs):
            if len(inputs) == 0:
                continue
            sum_config.connections.append(pb.SumConnectionConfig(inputs=inputs, output=sum_idx))

        if len(sum_config.connections) == 0:
            self.cc.pop_config()
            return

        for lane_idx, bit in enumerate(entity.upscaling):
            sum_config.upscales.append(pb.UpscaleConfig(lane=lane_idx, enabled=bit))

    @Serializer._serialize.register
    def _(self, entity: UBlock):
        select_config = self.cc.new_config(entity).select_config
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
            self.cc.pop_config()
        else:
            pass

    @Serializer._serialize.register
    def _(self, entity: TBlock):
        switch_config = self.cc.new_config(entity).switch_config
        for idx, state in enumerate(entity.muxes):
            if idx is None:
                continue
            switch_config.muxes.append(pb.Mux(state=state))

        if len(switch_config.muxes) == 0:
            self.cc.pop_config()

        use_config = self.cc.new_config(entity).use_config
        for idx, (uses, source, target_upscaled) in enumerate(zip(entity.uses, entity.sources, entity.targets_upscaled)):
            if source is None:
                continue
            use_config.uses.extend([pb.Use(idx=idx, count=uses, source=source, upscaled=target_upscaled) ])

        if len(use_config.uses) == 0:
            self.cc.pop_config()

class REDACDeserializer(Deserializer):

    def __init__(self, computer: "REDAC"):
        super().__init__(computer)

    def config_type(self) -> type:
        return List[pb.Config]

    def deserialize(self, config: Dict[str, Any] | List[pb.Config]):
        """
        Deserializes a list of protobuf configs and applies them to the analog computer.
        """
        for conf in config:
            # Store full config so overloads can access entity path
            self._current_full_config = conf

            # Extract the specific config type from the oneof and dispatch
            config_kind = conf.WhichOneof('kind')
            if config_kind:
                specific_config = getattr(conf, config_kind)
                self._deserialize(specific_config)

    @Deserializer._deserialize.register
    def _(self, config: pb.AdcConfig):
        """Deserialize ADC configuration and apply to Carrier."""
        entity_path = Path.parse(self._current_full_config.entity.path)
        entity = self.computer.get_entity(entity_path)

        adc_channels = []
        for channel in config.channels:
            adc_channels.append(ADCChannel(
                index=channel.idx,
                gain=channel.gain,
                offset=channel.offset
            ))
        entity.adc_config = adc_channels

    @Deserializer._deserialize.register
    def _(self, config: pb.PortConfig):
        """Deserialize port configuration and apply to Carrier."""
        entity_path = Path.parse(self._current_full_config.entity.path)
        entity = self.computer.get_entity(entity_path)

        acl_select = []
        for state in config.states:
            if state == pb.PortConfig.AclState.EXTERNAL:
                acl_select.append("external")
            else:
                acl_select.append("internal")
        entity.acl_select = acl_select

    @Deserializer._deserialize.register
    def _(self, config: pb.CoefConfig):
        """Deserialize coefficient configuration and apply to CBlock."""
        entity_path = Path.parse(self._current_full_config.entity.path)
        entity = self.computer.get_entity(entity_path)

        for element in config.elements:
            entity.elements[element.idx].computation.factor = element.factor

    @Deserializer._deserialize.register
    def _(self, config: pb.ItorConfig):
        """Deserialize integrator configuration and apply to MIntBlock."""
        entity_path = Path.parse(self._current_full_config.entity.path)
        entity = self.computer.get_entity(entity_path)

        for element in config.elements:
            entity.elements[element.idx].ic = element.ic
            entity.elements[element.idx].k = element.k

    @Deserializer._deserialize.register
    def _(self, config: pb.LimiterConfig):
        """Deserialize limiter configuration and apply to MIntBlock."""
        entity_path = Path.parse(self._current_full_config.entity.path)
        entity = self.computer.get_entity(entity_path)

        limiters = [False] * len(entity.limiters)
        for element in config.elements:
            limiters[element.idx] = element.enable
        entity.limiters = limiters

    @Deserializer._deserialize.register
    def _(self, config: pb.SumConfig):
        """Deserialize sum configuration and apply to IBlock."""
        entity_path = Path.parse(self._current_full_config.entity.path)
        entity = self.computer.get_entity(entity_path)

        # Initialize empty outputs
        outputs = [set() for _ in range(len(entity.outputs))]
        for connection in config.connections:
            outputs[connection.output] = set(connection.inputs)
        entity.outputs = outputs

        # Deserialize upscaling
        upscaling = [False] * len(entity.upscaling)
        for upscale in config.upscales:
            upscaling[upscale.lane] = upscale.enabled
        entity.upscaling = upscaling

    @Deserializer._deserialize.register
    def _(self, config: pb.SelectConfig):
        """Deserialize select configuration and apply to UBlock."""
        entity_path = Path.parse(self._current_full_config.entity.path)
        entity = self.computer.get_entity(entity_path)

        # Deserialize constant
        if config.constant == pb.SelectConfig.ConstantConfig.GROUND:
            entity.constant = False
        else:
            sign = 1.0 if config.constant == pb.SelectConfig.ConstantConfig.POS_REF else -1.0
            magnitude = 1.0 if config.magnitude == pb.SelectConfig.Magnitude.ONE else 0.1
            entity.constant = sign * magnitude

        # Deserialize connections
        outputs = [None] * len(entity.outputs)
        for connection in config.connections:
            outputs[connection.output] = connection.input
        entity.outputs = outputs

    @Deserializer._deserialize.register
    def _(self, config: pb.SwitchConfig):
        """Deserialize switch configuration and apply to TBlock."""
        entity_path = Path.parse(self._current_full_config.entity.path)
        entity = self.computer.get_entity(entity_path)

        muxes = []
        for mux in config.muxes:
            if mux.HasField('state'):
                muxes.append(mux.state)
        if muxes:
            entity.muxes = muxes

    @Deserializer._deserialize.register
    def _(self, config: pb.UseConfig):
        """Deserialize use configuration and apply to TBlock."""
        entity_path = Path.parse(self._current_full_config.entity.path)
        entity = self.computer.get_entity(entity_path)

        sources = [None] * len(entity.sources)
        uses = [0] * len(entity.uses)
        targets_upscaled = [False] * len(entity.targets_upscaled)

        for use in config.uses:
            uses[use.idx] = use.count
            if use.HasField('source'):
                sources[use.idx] = use.source
            targets_upscaled[use.idx] = use.upscaled

        entity.sources = sources
        entity.uses = uses
        entity.targets_upscaled = targets_upscaled

    
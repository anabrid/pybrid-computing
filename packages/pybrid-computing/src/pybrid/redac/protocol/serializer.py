# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later
import logging
import string
import typing
from functools import singledispatchmethod
from typing import List, Any, Dict

from pybrid.redac.router import Tracer
from pybrid.base.hybrid.computer import AnalogComputer
from pybrid.base.hybrid.entities import Entity
from pybrid.base.proto import main_pb2 as pb
from pybrid.redac.blocks import CBlock, MMulBlock, TBlock, MIntBlock, UBlock, IBlock
from pybrid.redac.carrier import Carrier, ADCChannel
from pybrid.redac.blocks.backplane_tblock import BackplaneTBlock
from pybrid.redac.cluster import Cluster
from pybrid.redac.device import Device
from pybrid.redac.elements import ComputationElement
from pybrid.redac.entities import Path, Loc, EntityType, EntityClass

from pybrid.base.hybrid.serializer import Serializer, Deserializer

logger = logging.getLogger(__name__)

_CONFIG_TYPE = Dict[str, Any] | List[pb.Item]


class REDACSerializer(Serializer):
    """Unified serializer for REDAC entity-tree specification and operational configuration."""

    def __init__(self):
        super().__init__()
        from pybrid.redac.protocol.validators import AdcProbeValidator
        self.validators.append(AdcProbeValidator())

    ###
    # Configuration
    ###

    @singledispatchmethod
    def _serialize_configuration(self, entity: Entity):
        return super()._serialize_configuration(entity)

    @_serialize_configuration.register
    def _(self, entity: ComputationElement):
        return None

    @_serialize_configuration.register
    def _(self, entity: Carrier):
        adc_config = self.cc.new_config(entity).adc_config
        adc_channels = adc_config.channels

        for adc_channel in entity.adc_config:
            if adc_channel is not None:
                pb_adc_channel = adc_channels.add()
                pb_adc_channel.idx = adc_channel.index
                pb_adc_channel.gain = adc_channel.gain
                pb_adc_channel.offset = adc_channel.offset
                pb_adc_channel.probe = adc_channel.probe

        # need to send "global" ACL_SELECT value to first carrier
        if entity.acl_select:
            acl_config = self.cc.new_config(entity).port_config
            acl_select = acl_config.states

            for interface in entity.acl_select:
                acl_select.append(pb.PortConfig.AclState.EXTERNAL if \
                    interface.lower() == "external" else pb.PortConfig.AclState.INTERNAL)

    @_serialize_configuration.register
    def _(self, entity: CBlock):
        coef_config = self.cc.new_config(entity).coef_config
        elements = coef_config.elements
        for elem_idx, element in enumerate(entity.elements):
            elements.append(pb.CoefConfig.Element(idx=elem_idx, factor=element.computation.factor))

    @_serialize_configuration.register
    def _(self, entity: MMulBlock):
        pass

    @_serialize_configuration.register
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

    @_serialize_configuration.register
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

    @_serialize_configuration.register
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

    @_serialize_configuration.register
    def _(self, entity: TBlock):
        switch_config = self.cc.new_config(entity).switch_config
        for idx, state in enumerate(entity.muxes):
            if idx is None:
                continue
            switch_config.muxes.append(pb.Mux(state=state))

        if len(switch_config.muxes) == 0:
            self.cc.pop_config()

    @_serialize_configuration.register
    def _(self, entity: BackplaneTBlock):
        switch_config = self.cc.new_config(entity).bpl_switch_config
        for idx, state in enumerate(entity.muxes):
            if idx is None:
                continue
            switch_config.muxes.append(pb.Mux(state=state))

        if len(switch_config.muxes) == 0:
            self.cc.pop_config()

    @staticmethod
    def _make_version(version) -> pb.Version:
        """Convert a packaging.version.Version to pb.Version, or return a zero version."""
        if version is None:
            return pb.Version()
        return pb.Version(major=version.major, minor=version.minor, patch=version.micro)

    @staticmethod
    def _entity_id(entity) -> str:
        """Return the wire-format entity ID with leading '/'."""
        return "/" + str(entity.path.id_)

    ###
    # Specification
    ###

    @singledispatchmethod
    def _serialize_specification(self, entity: Entity) -> pb.Entity:
        return super()._serialize_specification(entity)

    @_serialize_specification.register
    def _(self, entity: Device) -> pb.Entity:
        """Serialize a Device as a DEVICE-class pb.Entity containing carrier children."""
        pb_entity = pb.Entity(
            id=self._entity_id(entity),
            class_=pb.Entity.DEVICE,
        )
        for carrier in entity.carriers:
            pb_entity.children.append(self.serialize_specification(carrier))
        return pb_entity

    @_serialize_specification.register
    def _(self, entity: Carrier) -> pb.Entity:
        """Serialize a Carrier as a CARRIER-class pb.Entity with cluster and optional block children."""
        et = entity.entity_type
        if et is not None:
            class_ = et.class_.value
            type_ = et.type_ or 0
            variant = et.variant or 0
            version = self._make_version(et.version)
        else:
            class_ = pb.Entity.CARRIER
            type_ = 0
            variant = 0
            version = pb.Version()

        pb_entity = pb.Entity(
            id=self._entity_id(entity),
            class_=class_,
            type=type_,
            variant=variant,
            version=version,
        )

        if entity.location:
            pb_entity.location_v0.stack = entity.location.path[0]
            pb_entity.location_v0.carrier = entity.location.path[1]

        for cluster in entity.clusters:
            pb_entity.children.append(self.serialize_specification(cluster))
        if entity.tblock:
            pb_entity.children.append(self.serialize_specification(entity.tblock))
        if entity.st0block:
            pb_entity.children.append(self.serialize_specification(entity.st0block))
        if entity.st1block:
            pb_entity.children.append(self.serialize_specification(entity.st1block))
        if entity.st2block:
            pb_entity.children.append(self.serialize_specification(entity.st2block))
        if entity.front_plane:
            pb_entity.children.append(self.serialize_specification(entity.front_plane))

        return pb_entity

    @_serialize_specification.register
    def _(self, entity: Cluster) -> pb.Entity:
        """Serialize a Cluster as a CLUSTER-class pb.Entity with block children."""
        et = entity.entity_type
        if et is not None:
            class_ = et.class_.value
            type_ = et.type_ or 0
            variant = et.variant or 0
            version = self._make_version(et.version)
        else:
            class_ = pb.Entity.CLUSTER
            type_ = 0
            variant = 0
            version = pb.Version()

        pb_entity = pb.Entity(
            id=self._entity_id(entity),
            class_=class_,
            type=type_,
            variant=variant,
            version=version,
        )

        for block in entity.children:
            pb_entity.children.append(self.serialize_specification(block))

        return pb_entity

    def _serialize_specification_function_block(self, entity) -> pb.Entity:
        """Default specification serializer for FunctionBlock leaf nodes."""
        et = getattr(entity, "entity_type", None)
        if et is None:
            et = EntityType.reverse_lookup(type(entity))
        version = self._make_version(et.version)
        return pb.Entity(
            id=self._entity_id(entity),
            class_=et.class_.value,
            type=et.type_ or 0,
            variant=et.variant or 0,
            version=version,
        )

    def serialize_specification(self, entity: Entity) -> pb.Entity:
        """Serialize specification; fall back to FunctionBlock handler for unregistered types."""
        try:
            return self._serialize_specification(entity)
        except NotImplementedError:
            return self._serialize_specification_function_block(entity)

    def serialize_dependency_info(self, computer: AnalogComputer):
        """
        Serialize dependency information used for beyond carrier calibration.
        It constains information where a signal is coming from and where it is going to.
        """
        from pybrid.redac import REDAC
        if not isinstance(computer, REDAC):
            return
        tracer = Tracer()

        traces = []
        cluster2node_map: typing.Dict[Loc, pb.Node] = dict()

        def cluster2node(loc: Loc):
            if loc in cluster2node_map:
                node = cluster2node_map[loc]
            else:
                node = cluster2node_map[loc] = len(cluster2node_map)
            return node

        for carrier in computer.carriers:
            for cluster in carrier.clusters:
                cluster2node(cluster.loc())
                tracer.add_carrier(carrier)

        def add_sink(src_loc: Loc, sink_loc: Loc, upscaled: bool):
            traces.append(pb.Trace(
                source_node=cluster2node(src_loc.cluster()),
                source_lane=src_loc.lane_id(),
                sink_node=cluster2node(sink_loc.cluster()),
                sink_lane=sink_loc.lane_id(),
                sink_upscaled=upscaled
            ))

        for carrier in computer.carriers:
            for cluster in carrier.clusters:
                for lane_idx in range(0, 32):
                    target_loc = cluster.loc() / lane_idx
                    source_loc = tracer.find_coef(target_loc)

                    if source_loc is None:
                        continue

                    src_carrier = computer.carriers[source_loc.carrier_id()]
                    if src_carrier is None:
                        continue
                    src_cluster = src_carrier.clusters[source_loc.cluster_id()]
                    if src_cluster is None:
                        continue
                    coef = src_cluster.cblock.elements[source_loc.lane_id()]
                    if coef.factor == 0.0:
                        continue

                    upscaled = cluster.iblock.upscaling[target_loc.lane_id()]
                    add_sink(source_loc, target_loc, upscaled)

        dependency_info = pb.DependencyInfo()
        for carrier in computer.carriers:
            for cluster in carrier.clusters:
                dependency_info.entity_ids.append(pb.EntityId(path=str(cluster.path)))

        for carrier in computer.carriers:
            for cluster in carrier.clusters:
                config = self.cc.new_config(carrier).dependency_info
                config.CopyFrom(dependency_info)
                cluster_node = cluster2node(cluster.loc())

                for trace in traces:
                    if cluster_node in (trace.source_node, trace.sink_node):
                        config.traces.append(trace)

    def serialize_additional(self, computer: AnalogComputer):
        self.serialize_dependency_info(computer)
        #self.serialize_ip_lookup_table()


class REDACDeserializer(Deserializer):
    """Unified deserializer for REDAC entity-tree specification and operational configuration."""

    # Registry: EntityClass enum → method name (str).
    # Subclasses extend via dict merge: {**REDACDeserializer._spec_handlers, ...}
    _spec_handlers: dict = {
        EntityClass.DEVICE: "_spec_device",
        EntityClass.CARRIER: "_spec_carrier",
        EntityClass.CLUSTER: "_spec_cluster",
    }

    def __init__(self, computer=None):
        super().__init__(computer)

    def deserialize_specification(self, entity: pb.Entity, path: Path, location: Loc = None) -> Entity:
        """Resolve handler by EntityClass, fall back to generic function-block handler."""
        class_ = EntityClass(entity.class_)
        handler_name = self._spec_handlers.get(class_)
        if handler_name is not None:
            return getattr(self, handler_name)(entity, path, location)
        return self._spec_function_block(entity, path, location)

    def _spec_device(self, entity: pb.Entity, path: Path, location: Loc) -> Device:
        """Deserialize DEVICE: iterate carrier children via dispatch."""
        assert location is None
        carriers = []
        for child in entity.children:
            carrier_path = Path.parse(child.id)
            carriers.append(self.deserialize_specification(child, carrier_path))
        return Device(backplane=None, carriers=carriers, path=path)

    def _spec_carrier(self, entity: pb.Entity, path: Path, location: Loc = None) -> Carrier:
        """Deserialize CARRIER: collect clusters/T-blocks/FP via dispatch, construct all-at-once."""
        this_entity_type = EntityType.pop_from_dict(entity)
        assert this_entity_type.class_ is EntityClass.CARRIER

        clusters = []
        tblock = None
        st0block = None
        st1block = None
        st2block = None
        front_plane = None
        acl_select = None

        if entity.HasField("location_v0"):
            location = Loc.new_carrier(entity.location_v0.stack, entity.location_v0.carrier)

        stack_loc = location.stack() if location is not None else None
        for child in entity.children:
            path_: Path = path / Path.parse(child.id)
            if not path_.id_:
                logger.warning("Reported entities include nameless entity at %s: %s", path_, child)
            elif path_.id_ == "T":
                tblock = self._spec_function_block(child, path_, stack_loc)
            elif path_.id_ == "ST0":
                st0block = self._spec_function_block(child, path_, stack_loc)
            elif path_.id_ == "ST1":
                st1block = self._spec_function_block(child, path_, stack_loc)
            elif path_.id_ == "ST2":
                st2block = self._spec_function_block(child, path_, stack_loc)
            elif path_.id_ == "FP":
                result = self._handle_unknown_carrier_child(path_, child)
                if result is not None:
                    front_plane, acl_select = result
            elif path_.id_ in string.digits:
                clusters.append(self.deserialize_specification(
                    child,
                    path_,
                    location / int(path_.id_) if location is not None else None
                ))

        return Carrier(
            path=path,
            clusters=clusters,
            tblock=tblock,
            st0block=st0block,
            st1block=st1block,
            st2block=st2block,
            front_plane=front_plane,
            acl_select=acl_select,
            location=location,
            entity_type=this_entity_type,
        )

    def _spec_cluster(self, entity: pb.Entity, path: Path, location: Loc) -> Cluster:
        """Deserialize CLUSTER: collect block children, construct with all required fields."""
        this_entity_type = EntityType.pop_from_dict(entity)
        assert this_entity_type.class_ is EntityClass.CLUSTER

        blocks = dict()
        for child in entity.children:
            path_ = path / Path.parse(child.id)
            block = self._spec_function_block(child, path_, location)
            blocks[f"{path_.id_.lower()}block"] = block

        # Optional blocks default to None when absent from the serialized entity tree.
        blocks.setdefault("m0block", None)
        blocks.setdefault("m1block", None)
        blocks.setdefault("shblock", None)

        return Cluster(
            path=path,
            location=location,
            entity_type=this_entity_type,
            **blocks
        )

    def _spec_function_block(self, entity: pb.Entity, path: Path, location: Loc):
        """Default: use EntityType registry for concrete class lookup."""
        this_entity_type = EntityType.pop_from_dict(entity)
        entity_class = EntityType.lookup(this_entity_type, decay=True)
        block = entity_class(path=path, location=location)
        block.entity_type = this_entity_type
        return block

    def _handle_unknown_carrier_child(self, path: Path, child: pb.Entity):
        """Hook for subclasses to handle carrier children not recognized by REDAC (e.g. FP).

        Returns a (front_plane, acl_select) tuple on success, or None to skip.
        """
        logger.warning("Unknown carrier child at %s: %s", path, child)
        return None

    @singledispatchmethod
    def _deserialize_configuration(self, config):
        return super()._deserialize_configuration(config)

    @_deserialize_configuration.register
    def _(self, config: pb.AdcConfig):
        """Deserialize ADC configuration and apply to Carrier."""
        entity_path = Path.parse(self._current_full_config.entity.path)
        entity = self.computer.get_entity(entity_path)

        adc_channels = []
        for channel in config.channels:
            adc_channels.append(ADCChannel(
                index=channel.idx,
                gain=channel.gain,
                offset=channel.offset,
                probe=channel.probe
            ))
        entity.adc_config = adc_channels

    @_deserialize_configuration.register
    def _(self, config: pb.CoefConfig):
        """Deserialize coefficient configuration and apply to CBlock."""
        entity_path = Path.parse(self._current_full_config.entity.path)
        entity = self.computer.get_entity(entity_path)

        for element in config.elements:
            entity.elements[element.idx].computation.factor = element.factor

    @_deserialize_configuration.register
    def _(self, config: pb.ItorConfig):
        """Deserialize integrator configuration and apply to MIntBlock."""
        entity_path = Path.parse(self._current_full_config.entity.path)
        entity = self.computer.get_entity(entity_path)

        for element in config.elements:
            entity.elements[element.idx].ic = element.ic
            entity.elements[element.idx].k = element.k

    @_deserialize_configuration.register
    def _(self, config: pb.LimiterConfig):
        """Deserialize limiter configuration and apply to MIntBlock."""
        entity_path = Path.parse(self._current_full_config.entity.path)
        entity = self.computer.get_entity(entity_path)

        limiters = [False] * len(entity.limiters)
        for element in config.elements:
            limiters[element.idx] = element.enable
        entity.limiters = limiters

    @_deserialize_configuration.register
    def _(self, config: pb.SumConfig):
        """Deserialize sum configuration and apply to IBlock."""
        entity_path = Path.parse(self._current_full_config.entity.path)
        entity = self.computer.get_entity(entity_path)

        outputs = [set() for _ in range(len(entity.outputs))]
        for connection in config.connections:
            outputs[connection.output] = set(connection.inputs)
        entity.outputs = outputs

        upscaling = [False] * len(entity.upscaling)
        for upscale in config.upscales:
            upscaling[upscale.lane] = upscale.enabled
        entity.upscaling = upscaling

    @_deserialize_configuration.register
    def _(self, config: pb.SelectConfig):
        """Deserialize select configuration and apply to UBlock."""
        entity_path = Path.parse(self._current_full_config.entity.path)
        entity = self.computer.get_entity(entity_path)

        if config.constant == pb.SelectConfig.ConstantConfig.GROUND:
            entity.constant = False
        else:
            sign = 1.0 if config.constant == pb.SelectConfig.ConstantConfig.POS_REF else -1.0
            magnitude = 1.0 if config.magnitude == pb.SelectConfig.Magnitude.ONE else 0.1
            entity.constant = sign * magnitude

        outputs = [None] * len(entity.outputs)
        for connection in config.connections:
            outputs[connection.output] = connection.input
        entity.outputs = outputs

    @_deserialize_configuration.register
    def _(self, config: pb.SwitchConfig):
        """Deserialize switch configuration and apply to TBlock."""
        entity_path = Path.parse(self._current_full_config.entity.path)
        entity = self.computer.get_entity(entity_path)

        muxes = []
        for mux in config.muxes:
            muxes.append(mux.state)
        if muxes:
            entity.muxes = muxes

    @_deserialize_configuration.register
    def _(self, config: pb.BPLSwitchConfig):
        """Deserialize switch configuration and apply to TBlock."""
        entity_path = Path.parse(self._current_full_config.entity.path)
        entity = self.computer.get_entity(entity_path)

        muxes = []
        for mux in config.muxes:
            muxes.append(mux.state)
        if muxes:
            entity.muxes = muxes

    @_deserialize_configuration.register
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



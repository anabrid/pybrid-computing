# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later
import queue
from abc import ABC
from functools import singledispatchmethod
from typing import List

from pybrid.base.hybrid.computer import AnalogComputer
from pybrid.base.hybrid.entities import Entity, Path
from pybrid.base.hybrid.validators import ConfigValidator
from pybrid.base.proto import main_pb2 as pb


class Serializer(ABC):
    """Unified serializer for both entity-tree specification and operational configuration."""

    def __init__(self):
        self.validators: list = []

    def add_validator(self, validator: ConfigValidator):
        self.validators.append(validator)

    class ConfigCollector:
        configs: List[pb.Item]

        def __init__(self, configs: List[pb.Item]):
            self.items = configs

        def add_config(self, config: pb.Item):
            self.items.append(config)

        def new_config(self, entity: Entity) -> pb.Item:
            config = pb.Item(entity=pb.EntityId(path=str(entity.path)))
            self.add_config(config)
            return config

        def pop_config(self) -> pb.Item:
            return self.items.pop()

    def serialize(self, computer: AnalogComputer, skip_validation: bool = False) -> pb.Module:
        """Produce a full module: specification entries first, then configuration entries."""

        if not skip_validation:
            all_errors: list[str] = []

            for v in self.validators:
                result = v.validate(computer)
                if not result.ok:
                    all_errors.append(result.error)

            if all_errors:
                raise ValueError(
                    f"Validation failed with {len(all_errors)} error(s):\n" + "\n".join(f"  - {e}" for e in all_errors)
                )

        items = []

        for entity in computer.entities:
            pb_entity = self.serialize_specification(entity)
            config = pb.Item(entity=pb.EntityId(path=str(entity.path)))
            config.entity_specification.entity.CopyFrom(pb_entity)
            items.append(config)

        items.extend(self.serialize_specification_payloads(computer))
        items.extend(self.serialize_configuration(computer))
        return pb.Module(items=items)

    def serialize_specification_payloads(self, computer: AnalogComputer) -> List[pb.Item]:
        """Hook for non-entity-tree specification items (e.g. wiring specifications).

        Subclasses override to emit additional spec-side Items whose payloads
        sit on a different oneof arm than ``entity_specification``.
        """
        return []

    def serialize_specification(self, entity: Entity) -> pb.Entity:
        """Serialize a single entity's specification (structure, not state)."""
        return self._serialize_specification(entity)

    def serialize_configuration(self, computer: AnalogComputer) -> List[pb.Item]:
        """Serialize operational state via BFS traversal over get_config_entities()."""
        self.cc = Serializer.ConfigCollector([])
        for top_entity in computer.get_config_entities():
            traversal = queue.Queue()
            traversal.put(top_entity)
            while not traversal.empty():
                entity = traversal.get()
                for child in entity.children:
                    traversal.put(child)
                self._serialize_configuration(entity)
        self.serialize_additional(computer)
        return self.cc.items

    def serialize_additional(self, computer: AnalogComputer):
        """Hook for cross-entity objects (e.g. UseConfig)."""
        pass

    @singledispatchmethod
    def _serialize_specification(self, entity: Entity) -> pb.Entity:
        """Dispatch on Python entity type for specification serialization."""
        raise NotImplementedError(f"No specification serializer registered for {type(entity)!r}")

    @singledispatchmethod
    def _serialize_configuration(self, entity: Entity):
        """Dispatch on Python entity type for configuration serialization."""
        return None


class Deserializer(ABC):
    """Unified deserializer for both entity-tree specification and operational configuration."""

    #: Set of ``Item.kind`` oneof field names that carry spec-level payloads.
    #: Subclasses extend this with their own kinds (e.g. ``wiring_specification``);
    #: the matching payload type must be registered on :meth:`_deserialize_specification`.
    SPEC_PAYLOAD_KINDS: set = {"entity_specification"}

    computer: AnalogComputer

    def __init__(self, computer: AnalogComputer = None):
        self.computer = computer

    def deserialize(self, module: pb.Module):
        """Process a full module: specification payloads first, then operational configuration."""
        spec_items = []
        op_configs = []
        for conf in module.items:
            if conf.WhichOneof("kind") in self.SPEC_PAYLOAD_KINDS:
                spec_items.append(conf)
            else:
                op_configs.append(conf)
        for conf in spec_items:
            self._current_full_config = conf
            kind = conf.WhichOneof("kind")
            self._deserialize_specification(getattr(conf, kind))
        self.deserialize_configuration(op_configs)

    @singledispatchmethod
    def _deserialize_specification(self, payload):
        """Dispatch on pb payload type for specification-level Items.

        Subclasses register arms for each ``SPEC_PAYLOAD_KINDS`` entry. The
        full enclosing :class:`pb.Item` is accessible via
        ``self._current_full_config`` for arms that need the entity path.
        """
        pass

    def deserialize_configuration(self, configs: List[pb.Item]):
        """Apply operational config entries to self.computer."""
        for conf in configs:
            self._current_full_config = conf
            config_kind = conf.WhichOneof("kind")
            if config_kind:
                self._deserialize_configuration(getattr(conf, config_kind))

    @singledispatchmethod
    def _deserialize_configuration(self, config):
        """Dispatch on pb config type for configuration deserialization."""
        pass


__all__ = [
    "Serializer",
    "Deserializer",
]

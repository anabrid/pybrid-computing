# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later
import queue
from typing import List
from functools import singledispatchmethod

from abc import ABC, abstractmethod
from pybrid.base.hybrid.computer import AnalogComputer
from pybrid.base.proto import main_pb2 as pb
from pybrid.base.hybrid.entities import Entity, Path
from pybrid.base.hybrid.validators import ConfigValidator

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
                    f"Validation failed with {len(all_errors)} error(s):\n"
                    + "\n".join(f"  - {e}" for e in all_errors)
                )
            
        # serialize specification and configuration in mixed mode
        items = []

        for entity in computer.entities:
            pb_entity = self.serialize_specification(entity)
            config = pb.Item(entity=pb.EntityId(path=str(entity.path)))
            config.entity_specification.entity.CopyFrom(pb_entity)
            items.append(config)

        items.extend(self.serialize_configuration(computer))
        return pb.Module(items=items)

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
        raise NotImplementedError(
            f"No specification serializer registered for {type(entity)!r}"
        )

    @singledispatchmethod
    def _serialize_configuration(self, entity: Entity):
        """Dispatch on Python entity type for configuration serialization."""
        return None


class Deserializer(ABC):
    """Unified deserializer for both entity-tree specification and operational configuration."""

    computer: AnalogComputer

    def __init__(self, computer: AnalogComputer = None):
        self.computer = computer

    def deserialize(self, module: pb.Module):
        """Process a full module: specification entries first, then configuration entries."""
        spec_configs = []
        op_configs = []
        for conf in module.items:
            if conf.WhichOneof('kind') == 'entity_specification':
                spec_configs.append(conf)
            else:
                op_configs.append(conf)
        for conf in spec_configs:
            entity = conf.entity_specification.entity
            path = Path.parse(conf.entity.path)
            self.deserialize_specification(entity, path)
        self.deserialize_configuration(op_configs)

    @abstractmethod
    def deserialize_specification(self, entity: pb.Entity, path: Path) -> Entity:
        """Deserialize a pb.Entity tree into Python entity objects."""
        ...

    def deserialize_configuration(self, configs: List[pb.Item]):
        """Apply operational config entries to self.computer."""
        for conf in configs:
            self._current_full_config = conf
            config_kind = conf.WhichOneof('kind')
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
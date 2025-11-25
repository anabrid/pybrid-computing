# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later
import queue
from typing import List, Dict, Any
from functools import singledispatchmethod

from abc import ABC, abstractmethod
from pybrid.base.hybrid.computer import AnalogComputer
from pybrid.base.proto import main_pb2 as pb
from pybrid.base.hybrid.entities import Entity

_CONFIG_TYPE = Dict[str, Any] | List[pb.Config]

class Serializer(ABC):
    """
    Given an entity, serializes its configuration into Protobuf format.
    """

    class ConfigCollector:
        configs : List[pb.Config]

        def __init__(self, configs: List[pb.Config]):
            self.configs = configs

        def new_config(self, entity: Entity) -> pb.Config:
            config = pb.Config(entity=pb.EntityId(path=str(entity.path)))
            self.configs.append(config)
            return config

        def pop_config(self) -> pb.Config:
            return self.configs.pop()
        
    @abstractmethod
    def config_type(self) -> type:
        pass
        
    @abstractmethod
    def serialize(self, computer: AnalogComputer) -> _CONFIG_TYPE:
        """
        Serializes the computer's configuration into the config fomat
        """
        pass

    @abstractmethod
    def serialize_entities(self, entities: List[Entity]) -> _CONFIG_TYPE:
        """
        Serializes the configuration of a single entity.
        """
        pass

    @singledispatchmethod
    def _serialize(self, entity: Entity):
        """
        Single-disptach function that generates configs for the given entity.
        """
        return None

class Deserializer(ABC):
    """
    Given a configuration
    """

    def __init__(self, computer: AnalogComputer):
        self.computer = computer

    @abstractmethod
    def config_type(self) -> type:
        pass

    @abstractmethod
    def deserialize(self, config: _CONFIG_TYPE):
        """
        Deserializes a config and applies it to the analog computer.
        """
        pass

    @singledispatchmethod
    def _deserialize(self, config: pb.Config):
        """
        Single-dispatch function that reads a config and applies its configuration
        to a device.
        """
        pass
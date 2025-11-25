# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

from typing import List
from abc import ABC, abstractmethod

from pybrid.base.hybrid.entities import Entity, Path, EntityDoesNotExist
from pybrid.base.hybrid.utils import build_entity_path_dict


class AnalogComputer(ABC):
    #: The hierarchy of this analog computer.
    hierarchy = (Entity, )

    #: The entities present in this analog computer.
    entities: list[Entity]
    _entities_by_path: dict[Path, Entity]

    def __init__(self, entities: list[Entity] = None) -> None:
        super().__init__()
        self.entities = entities or list()
        self._entities_by_path = build_entity_path_dict(self.entities)

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    def get_entity(self, path: Path) -> Entity:
        """Get an entity by path."""
        try:
            return self._entities_by_path[path]
        except KeyError:
            raise EntityDoesNotExist("Entity with path %s does not exist." % str(path))

    @abstractmethod
    def get_config_entities(self) -> List[Entity]:
        """
        Returns a list of all top-level entities that should be serialized into a configuration
        file to represent the machine's state. Serializers need to traverse the
        list and all the elements' children to obtain the full state.

        Other than using `.entities` directly, this might also contain entities
        on the c=global level, e.g., system configurations or simulator
        data.
        """
        pass

    @abstractmethod
    def global_entities(self) -> List[Entity]:
        """
        Returns a list of entities using the global namespace, e.g, the simulation
        config.
        """
        pass

    @abstractmethod
    def get_serializer_implementation(self) -> type:
        """
        Return stype of serializer implementation _natively_ used for this type of computer.
        Using different serializers might still work, but only deliver partial results
        or change the output format.
        """
        pass

    @abstractmethod
    def get_deserializer_implementation(self) -> type:
        """
        Return stype of deserializer implementation _natively_ used for this type of computer.
        Using different deserializers might still work, but only deliver partial results
        or change the output format.
        """

    def reset(self):
        for entity in self.entities:
            entity.reset()
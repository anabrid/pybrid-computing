# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

from abc import ABC, abstractmethod
from typing import List

from pybrid.base.hybrid.entities import Entity, EntityDoesNotExist, Path
from pybrid.base.hybrid.utils import build_entity_path_dict


class AnalogComputer(ABC):
    hierarchy = (Entity,)
    entities: list[Entity]
    _entities_by_path: dict[Path, Entity]

    def __init__(self, entities: list[Entity] = None) -> None:
        super().__init__()
        self.entities = entities or list()
        self._entities_by_path = build_entity_path_dict(self.entities)

    @property
    @abstractmethod
    def name(self) -> str: ...

    def get_entity(self, path: Path) -> Entity:
        """Get an entity by path."""
        try:
            return self._entities_by_path[path]
        except KeyError:
            raise EntityDoesNotExist("Entity with path %s does not exist." % str(path))

    @abstractmethod
    def get_config_entities(self) -> List[Entity]:
        """
        Returns all top-level entities to serialize, which may include
        global-level entities (e.g. simulator config) beyond `.entities`.
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
    def get_serializer(self) -> type:
        """Return the unified Serializer implementation for this computer type."""
        ...

    @abstractmethod
    def get_deserializer(self) -> type:
        """Return the unified Deserializer implementation for this computer type."""
        ...

    def reset(self):
        for entity in self.entities:
            entity.reset()

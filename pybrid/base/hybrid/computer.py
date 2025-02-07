# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

from abc import ABC, abstractmethod

from .entities import Entity, Path, EntityDoesNotExist
from .utils import build_entity_path_dict


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

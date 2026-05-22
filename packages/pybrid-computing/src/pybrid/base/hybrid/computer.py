# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Literal, Union

from pybrid.base.hybrid.entities import Entity, EntityDoesNotExist, Path
from pybrid.base.hybrid.utils import build_entity_path_dict

NamedPin = Literal["aux0", "aux1", "gen0", "gen1"]
_VALID_NAMED_PINS: frozenset[str] = frozenset(NamedPin.__args__)


def validate_named_pin(value: Union[NamedPin, int]) -> None:
    """Raise ``ValueError`` if ``value`` is a string outside the named-pin set."""
    if isinstance(value, str) and value not in _VALID_NAMED_PINS:
        allowed = "/".join(sorted(_VALID_NAMED_PINS))
        raise ValueError(
            f"invalid named pin {value!r}; expected one of {allowed} or an int"
        )


@dataclass(frozen=True)
class WiringSpec:
    """Declares a physical analog patch between two carrier endpoints.

    Each field uses the flat encoding: entity path (MAC string) and a pin that
    is either an integer index or a named-pin string (see :data:`NamedPin`).
    Signal flows from source to target.
    """

    source_entity_path: str
    source_pin: Union[NamedPin, int]
    target_entity_path: str
    target_pin: Union[NamedPin, int]

    def __post_init__(self) -> None:
        validate_named_pin(self.source_pin)
        validate_named_pin(self.target_pin)


class AnalogComputer(ABC):
    hierarchy = (Entity,)
    entities: list[Entity]
    _entities_by_path: dict[Path, Entity]

    def __init__(self, entities: list[Entity] = None) -> None:
        super().__init__()
        self.entities = entities or list()
        self._entities_by_path = build_entity_path_dict(self.entities)
        self.wiring_specs: list[WiringSpec] = []

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
        self.wiring_specs.clear()

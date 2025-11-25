# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later
import typing
from dataclasses import dataclass
from typing import Iterable


class EntityDoesNotExist(Exception):
    pass


class Path(tuple):
    SCHEMA = None

    @classmethod
    def __get_pydantic_core_schema__(cls, _source_type, _handler):
        """Pydantic v2 schema generation"""
        from pydantic_core import core_schema
        return core_schema.no_info_before_validator_function(
            cls._pydantic_validate,
            core_schema.any_schema()
        )

    @classmethod
    def _pydantic_validate(cls, value):
        """Validate and convert value to Path instance"""
        if isinstance(value, cls):
            return value
        if isinstance(value, (list, tuple)):
            return cls(value)
        if isinstance(value, str):
            return cls.parse(value)
        raise ValueError(f"Cannot convert {type(value)} to Path")

    @property
    def parent(self):
        return Path(self[:-1])

    @property
    def id_(self):
        return self[-1]

    @property
    def root(self):
        return self[0]

    def to_root(self):
        """Returns the path until the root entity level."""
        return type(self)(self[:1])

    def to_parent(self):
        """Returns the path until the parent entity level."""
        return Path(self[:-1])

    @property
    def depth(self):
        return len(self)

    @classmethod
    def make_root(cls, root):
        root_ = cls._parse_part(0, root)
        return cls((root_,))

    @classmethod
    def _parse_part(cls, depth, part):
        if not cls.SCHEMA:
            return part
        return cls.SCHEMA[depth](part)

    @classmethod
    def make(cls, *parts):
        parts_ = (cls._parse_part(depth_, part_) for depth_, part_ in enumerate(parts))
        return cls(parts_)

    def __itruediv__(self, other):
        return self.join(other)

    def join(self, other):
        """Concatenates another path to this one and returns a copy."""
        if isinstance(other, Path):
            return Path(self + other)
        elif isinstance(other, str) or not isinstance(other, Iterable):
            return Path(self + (other,))
        else:
            return Path(self + tuple(other))

    def __truediv__(self, other):
        return self.join(other)

    @classmethod
    def parse(
        cls,
        path: typing.Union["Path", str],
        aliases: typing.Optional[dict[str, "Path"]] = None,
    ):
        if isinstance(path, Path):
            return path
        if isinstance(path, str):
            path = path.strip("/")
            if path == "":
                return cls.make()

            parts = path.split("/")
            # Paths may not have a trailing slash
            if not parts:
                raise ValueError("Empty path.")
            # Paths may start with an alias
            if aliases and (alias := aliases.get(parts[0], None)) is not None:
                parts = (*alias, *parts[1:])
            # Combine from split parts
            return cls.make(*parts)

        raise TypeError("Paths can be parsed only from strings.")

    def __str__(self):
        return "/".join(map(str, self))


@dataclass(kw_only=True)
class Entity:
    path: Path

    def __post_init__(self):
        if not isinstance(self.path, Path):
            self.path = Path.parse(self.path)

    @property
    def id_(self):
        """ID of the object, which is the last element of its path. Not necessarily unique."""
        return self.path[-1]

    @property
    def children(self) -> list["Entity"]:
        """Generator iterating through child entities."""
        yield from ()

    def __hash__(self):
        return hash(self.path)

    def __eq__(self, other):
        return self.path == other.path

    def reset(self):
        for child in self.children:
            child.reset()
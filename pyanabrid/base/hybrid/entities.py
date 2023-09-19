# Copyright (c) 2022 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
#
# This file is part of the pyanabrid software packet.
#
# ANABRID_BEGIN_LICENSE:GPL
# Commercial License Usage
# Licensees holding valid commercial anabrid licenses may use this file in
# accordance with the commercial license agreement provided with the
# Software or, alternatively, in accordance with the terms contained in
# a written agreement between you and Anabrid GmbH. For licensing terms
# and conditions see https://www.anabrid.com/licensing. For further
# information use the contact form at https://www.anabrid.com/contact.
#
# GNU General Public License Usage
# Alternatively, this file may be used under the terms of the GNU
# General Public License version 3 as published by the Free Software
# Foundation and appearing in the file LICENSE.GPL3 included in the
# packaging of this file. Please review the following information to
# ensure the GNU General Public License version 3 requirements
# will be met: https://www.gnu.org/licenses/gpl-3.0.html.
# For Germany, additional rules exist. Please consult /LICENSE.DE
# for further agreements.
# ANABRID_END_LICENSE
import typing
from typing import Iterable

from dataclasses import dataclass


class EntityDoesNotExist(Exception):
    pass


class Path(tuple):
    SCHEMA = None

    @property
    def parent(self):
        return Path(self[:-1])

    @property
    def id_(self):
        return self[-1]

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
    def parse(cls, path: typing.Union["Path", str], aliases: typing.Optional[dict[str, "Path"]] = None):
        if isinstance(path, Path):
            return path
        if isinstance(path, str):
            parts = path.split('/')
            # Paths may not have a trailing slash
            if not parts[-1]:
                raise ValueError("Invalid trailing slash in path string.")
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

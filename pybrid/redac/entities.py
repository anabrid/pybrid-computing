# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
The REDAC analog computer consists of a hierarchical structure of hardware modules.

This structure is represented by a tree-like structure of :class:`Entity` objects and their sub-classes.
Each entity has a unique :class:`Path` defining its position in this hierarchy.
You can iterate over the children of an entity via its :attr:`Entity.children` property.
As described in :class:`Path`, the hierarchy represented is as follows.

#. Carrier boards implemented by :class:`pybrid.redac.carrier.Carrier`
#. Clusters implemented by :class:`pybrid.redac.cluster.Cluster`
#. Function blocks implemented by :class:`pybrid.redac.blocks.FunctionBlock`, see :doc:`configurations`
#. Functions (Elements) implemented by :class:`pybrid.redac.elements.ComputationElement`
"""

from dataclasses import dataclass, fields, replace
from enum import Enum
import typing

from pybrid.base.hybrid import Path as BasePath
from pybrid.base.hybrid import Entity as BaseEntity


class UnknownEntityTypeError(ValueError):
    """Exception thrown when trying to get an unknown :class:`EntityType` instance."""
    pass


class EntityTypeRegistryError(ValueError):
    """Exception for errors inside the :class:`EntityType` registry."""
    pass


class EntityClass(Enum):
    """Entity class differentiates between carrier boards, different function blocks and so on. Max 5bit = 31."""
    CARRIER = 0
    CLUSTER = 1  # mostly unused
    MBLOCK = 2
    UBLOCK = 3
    CBLOCK = 4
    IBLOCK = 5
    OTHER = 31


_ENTITY_TYPE_REGISTRY: dict["EntityType", object] = dict()


@dataclass(kw_only=True, eq=True, frozen=True)
class EntityType:
    """
    A unique identifier for an entity type.

    Each hardware module in a REDAC analog computer contains hardware version information
    in their EEPROM. When the client library connects to an analog computer,
    it generally requests the tree of hardware modules present.
    This is given as a tree-like list of :class:`EntityType` objects.
    Since it is also automatically converted to the respective python objects,
    you typically do not need to handle :class:`EntityType` objects directly.

    One notable exception is registering a python class for the auto-conversion
    from an :class:`EntityType` to its respective :class:`Entity` class as follows.

    .. code-block::

        @EntityType.register(EntityClass.MBLOCK, 17, 3, 1)
        class ACustomMBlock(ElementBlock):
            ...
    """
    #: The class of the entity, see :class:`EntityClass`.
    #: Different classes of entities can only be placed at their expected slots and can not be interchanged.
    class_: EntityClass
    #: The type of the entity, mostly relevant for :class:`pybrid.redac.blocks.MBlock`.
    #: Different types of an entity have significantly different functionality, but may be placed in the same slots.
    type_: typing.Optional[int] = None
    #: The variant of an entity.
    #: Different variants of an entity have similar functionality, but may differ in certain implementation details.
    variant: typing.Optional[int] = None
    #: The version on an entity.
    #: Different versions of an entity are basically identical, but may contain different hardware elements or bugfixes.
    version: typing.Optional[int] = None

    @classmethod
    def pop_from_dict(cls, d):
        return cls(class_=EntityClass(d.pop("class")), type_=d.pop("type"), variant=d.pop("variant"),
                   version=d.pop("version"))

    def fallback_type(self):
        """Return a copy of this :class:`EntityType` with one more field set to None."""
        for field in reversed(fields(self)[1:]):
            if getattr(self, field.name) is not None:
                return replace(self, **{field.name: None})
        raise ValueError("Can not further decay.")

    @classmethod
    def register(cls, class_: EntityClass, type_, variant, version):
        """Register a class as an implementation of an :class:`EntityType`."""
        entity_type = cls(class_=class_, type_=type_, variant=variant, version=version)

        def register_(obj):
            if entity_type in _ENTITY_TYPE_REGISTRY:
                raise EntityTypeRegistryError("Entity type is already registered.")
            _ENTITY_TYPE_REGISTRY[entity_type] = obj
            return obj

        return register_

    @classmethod
    def lookup(cls, type_, decay=False):
        """
        Lookup the implementation of an :class:`EntityType`.
        Use the ``decay`` parameter if you want to allow finding a more generic implementation.
        """
        try:
            return _ENTITY_TYPE_REGISTRY[type_]
        except KeyError:
            if not decay:
                raise UnknownEntityTypeError("Entity type %s not registered." % type_)
            else:
                try:
                    return cls.lookup(type_.fallback_type(), True)
                except ValueError:
                    raise UnknownEntityTypeError("Neither entity type %s nor any fallbacks are registered." % type_)


class Path(BasePath):
    """
    A tuple uniquely identifying an entity in the REDAC.

    The path to an entity is a hierarchical combination of paths to its parent entities.
    Its structure in the REDAC is :code:`(<carrier board>, <cluster>, <block>, <function>)`.
    Carrier boards are defined by their MAC address, e.g. "04-E9-E5-14-74-BF".
    Clusters are defined by their index sent as a string, e.g. "0".
    Function blocks on them are identified by their abbreviation, one of "M0", "M1", "U", "C", "I".
    Functions on blocks are defined by their index as integer, e.g. 7.
    The blocks' functions are usually not directly accessed, but instead configured via their block.

    :Usage: Combine the identifiers to the required depth

        .. code-block::

            path_to_a_carrier_board = Path("00:00:5e:00:53:af")
            path_to_second_cluster_on_it = Path("00:00:5e:00:53:af", "1")
            path_to_m0_block_in_cluster0 = Path("00:00:5e:00:53:af", "0", "M0")
            path_to_first_func_on_block = Path("00:00:5e:00:53:af", "0", "M0", 0)
    """
    #: The schema defining the data types for the path's subcomponents.
    SCHEMA = (str, str, str, int)

    def to_carrier(self):
        """Returns the path until the carrier board level."""
        return Path(self[:1])

    def to_cluster(self):
        """
        Returns the path until the cluster level.

        Raises IndexError if path is not of sufficient depth.
        """
        return Path(self[:2])

    def to_block(self):
        """
        Returns the path until the block level.

        Raises IndexError if path is not of sufficient depth.
        """
        return Path(self[:3])

    def to_function(self):
        """
        Returns the path until the function level.

        Raises IndexError if path is not of sufficient depth.
        """
        return Path(self[:4])


@dataclass
class Entity(BaseEntity):
    """
    Base class for all entities inside a REDAC.
    """
    #: Unique path to this entity.
    path: Path

    @classmethod
    def create_from_entity_type_tree(cls, sub_path, sub_tree):
        raise NotImplementedError

    def generate_partial_configuration(self, attribute):
        if self.__dataclass_fields__.get(attribute, None):
            return {attribute: getattr(self, attribute)}
        else:
            raise ValueError("Unknown attribute %s for %s." % (attribute, self.__class__))

    def apply_partial_configuration(self, attribute, value):
        raise NotImplementedError

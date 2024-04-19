# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

from pybrid.base.hybrid import ComputationElement as BaseComputationElement

from .entities import Entity


class ComputationElement(BaseComputationElement, Entity):
    """
    A REDAC computation element (a function).

    Each computation element implements one of the available
    analog computations in :doc:`configurations`.
    """

    def generate_partial_configuration(self, attribute):
        if self.computation_class.__dataclass_fields__.get(attribute, None):
            return {attribute: getattr(self.computation, attribute)}
        else:
            raise ValueError("Unknown attribute %s for %s." % (attribute, self.__class__))

    def apply_partial_configuration(self, attribute, value):
        if field := self.computation_class.__dataclass_fields__.get(attribute, None):
            setattr(self.computation, attribute, field.type(value))
        else:
            raise ValueError("Unknown attribute %s for %s." % (attribute, self.__class__))

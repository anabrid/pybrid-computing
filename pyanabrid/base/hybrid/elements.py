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
from dataclasses import dataclass, field

from pyanabrid.base.analog import BaseComputation

from .entities import Entity


@dataclass(kw_only=True)
class BaseComputationElement(Entity):
    computation: BaseComputation

    def __hash__(self):
        return hash(self.path)

    def __setattr__(self, key, value):
        # Forward setting attributes to computation if possible
        if key != "computation" and hasattr(self, "computation") and hasattr(self.computation, key):
            setattr(self.computation, key, value)
        else:
            super().__setattr__(key, value)

    def __getattr__(self, item):
        # Forward getting attributes to computation if possible
        if item != "computation" and hasattr(self.computation, item):
            return getattr(self.computation, item)
        raise AttributeError


class ComputationElementMeta(type):
    """
    Allows using ComputationElement[Integration] to generate an integration element.
    """

    def __getitem__(self, computation: BaseComputation) -> typing.Type[BaseComputationElement]:
        # TODO: Clean this up :)
        return dataclass(
            type(
                computation.__name__ + 'Element', (self,),
                {"__annotations__": {"computation": computation,
                                     "computation_class": typing.ClassVar[typing.Type[computation]]},
                 "computation": field(default_factory=computation), "computation_class": computation,
                 "__hash__": BaseComputationElement.__hash__}
            )
        )


@dataclass(kw_only=True)
class ComputationElement(BaseComputationElement, metaclass=ComputationElementMeta):

    def __hash__(self):
        return hash(self.path)

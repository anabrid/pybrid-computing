# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import typing
from dataclasses import dataclass

from pybrid.base.proto import main_pb2 as pb
from pybrid.redac.elements import ComputationElement
from pybrid.redac.entities import Entity


class FunctionBlock(Entity):
    pass


@dataclass(kw_only=True)
class ElementBlock(FunctionBlock):
    """
    Base class for function blocks in a REDAC.
    """

    ELEMENTS: typing.ClassVar[list[typing.Type[ComputationElement]]] = None
    elements: typing.Optional[list[ComputationElement]] = None

    def __post_init__(self):
        super().__post_init__()
        if self.elements is None and self.ELEMENTS is not None:
            self.elements = [
                cls(path=self.path / idx) for idx, cls in enumerate(self.ELEMENTS)
            ]



class SignalConnectionError(Exception):
    pass


@dataclass
class SwitchingBlock(FunctionBlock):
    def connect(self, input, output, *outputs, force=False):
        raise NotImplementedError

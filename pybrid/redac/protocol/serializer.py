# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

from dataclasses import asdict
from functools import singledispatch

from ..blocks import ElementBlock, SwitchingBlock, CBlock
from ..elements import ComputationElement
from ..entities import Entity


def exclude(*fields):
    def _dict_factory_excluding(data):
        return {k: v for (k, v) in data if k not in fields}

    return _dict_factory_excluding


def build_config(entity: Entity, config: dict):
    entity_config, convert_children = to_dict(entity)
    config.update(entity_config)
    if convert_children:
        for child in entity.children:
            config["/" + str(child.id_)] = child_config = dict()
            build_config(child, child_config)
    return config


@singledispatch
def to_dict(entity: Entity):
    return {}, True


@to_dict.register
def _(entity: ComputationElement):
    return asdict(entity.computation), False


@to_dict.register
def _(entity: ElementBlock):
    return {"elements": [to_dict(element)[0] for element in entity.elements]}, False


@to_dict.register
def _(entity: CBlock):
    return {"elements": [element.computation.factor for element in entity.elements]}, False


@to_dict.register
def _(entity: SwitchingBlock):
    return asdict(entity, dict_factory=exclude('path')), False

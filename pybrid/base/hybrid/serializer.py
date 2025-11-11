# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later
import queue
import typing
from functools import singledispatch

from pybrid.base.proto import main_pb2 as pb
from pybrid.redac.entities import Entity

class ConfigCollector:
    configs : typing.List[pb.Config]

    def __init__(self, configs: typing.List[pb.Config]):
        self.configs = configs

    def new_config(self, entity: Entity) -> pb.Config:
        config = pb.Config(entity=pb.EntityId(path=str(entity.path)))
        self.configs.append(config)
        return config

    def pop_config(self) -> pb.Config:
        return self.configs.pop()

def build_config(entity: Entity) -> typing.List[pb.Config]:
    entities = queue.Queue()
    entities.put(entity)
    configs = []
    collector = ConfigCollector(configs)

    while not entities.empty():
        entity = entities.get()
        for child in entity.children:
            entities.put(child)
        to_pb(entity, collector)

    return configs

@singledispatch
def to_pb(entity: Entity, collector: ConfigCollector):
    return None
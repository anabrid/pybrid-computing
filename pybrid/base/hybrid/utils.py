# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later


from .entities import Entity, Path


def _add_to_entity_path_dict(d, entity):
    d[entity.path] = entity
    for child in entity.children:
        _add_to_entity_path_dict(d, child)


def build_entity_path_dict(
        entities: list[Entity], recursive=True
) -> dict[Path, Entity]:
    entities_by_path = dict()
    for entity in entities:
        _add_to_entity_path_dict(entities_by_path, entity)
    return entities_by_path

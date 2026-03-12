# Copyright (c) 2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import pytest

import pybrid.base.proto.main_pb2 as pb
from pybrid.redac.carrier import Carrier
from pybrid.redac.entities import Path, Loc
from pybrid.redac.protocol.serializer import REDACDeserializer


def _make_version() -> pb.Version:
    return pb.Version(major=1, minor=0, patch=0)


def _make_block_entity(block_id: str, class_val: int) -> pb.Entity:
    return pb.Entity(
        id=block_id,
        class_=class_val,
        type=1,
        variant=1,
        version=_make_version(),
        eui="00-00-00-00-00-00-00",
    )


def _make_cluster_entity(cluster_id: str = "0") -> pb.Entity:
    cluster = pb.Entity(
        id=cluster_id,
        class_=2,  # CLUSTER
        type=1,
        variant=1,
        version=_make_version(),
        eui="00-00-00-00-00-00-00",
    )
    cluster.children.append(_make_block_entity("M0", 3))
    cluster.children.append(_make_block_entity("U", 4))
    cluster.children.append(_make_block_entity("C", 5))
    cluster.children.append(_make_block_entity("I", 6))
    cluster.children.append(_make_block_entity("SH", 7))
    return cluster


def _make_carrier_entity(mac: str) -> pb.Entity:
    carrier = pb.Entity(
        id=mac,
        class_=1,  # CARRIER
        type=1,
        variant=1,
        version=_make_version(),
        eui="00-00-00-00-00-00-00",
    )
    carrier.children.append(_make_cluster_entity("0"))
    return carrier


class TestCarrierLocationFromEntity:

    def test_carrier_location_from_entity(self):
        mac = "AA-BB-CC-DD-EE-FF"
        entity = _make_carrier_entity(mac)
        entity.location_v0.stack = 1
        entity.location_v0.carrier = 4

        carrier = REDACDeserializer().deserialize_specification(entity, Path.parse(mac))

        assert carrier.location is not None
        assert carrier.location == Loc.new_carrier(1, 4)

    def test_carrier_location_none_when_no_location(self):
        mac = "AA-BB-CC-DD-EE-FF"
        entity = _make_carrier_entity(mac)
        carrier = REDACDeserializer().deserialize_specification(entity, Path.parse(mac))

        assert carrier.location is None

    def test_carrier_location_first_carrier(self):
        mac = "AA-BB-CC-DD-EE-FF"
        entity = _make_carrier_entity(mac)
        entity.location_v0.stack = 0
        entity.location_v0.carrier = 0

        carrier = REDACDeserializer().deserialize_specification(entity, Path.parse(mac))

        assert carrier.location is not None
        assert carrier.location == Loc.new_carrier(0, 0)

# Copyright (c) 2025 anabrid GmbH
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import pytest

from pybrid.base.hybrid.computer import WiringSpec
from pybrid.base.proto import main_pb2 as pb
from pybrid.lucidac.computer import LUCIStack
from pybrid.lucidac.protocol.serializer import LUCIDACDeserializer, LUCIDACSerializer
from pybrid.redac.blocks import CBlock, IBlock, MIntBlock, MMulBlock, UBlock
from pybrid.redac.blocks.shblock import SHBlock
from pybrid.redac.carrier import Carrier
from pybrid.redac.cluster import Cluster
from pybrid.redac.entities import Loc, Path


def _make_lucidac_carrier(mac: str, location_carrier: int = 0) -> Carrier:
    """Construct a minimal LUCIDAC-shaped carrier with one cluster."""
    carrier_path = Path.parse(mac)
    cluster_path = carrier_path / "0"
    cluster = Cluster(
        path=cluster_path,
        location=Loc.new_cluster(0, location_carrier, 0),
        m0block=MIntBlock(path=cluster_path / "M0"),
        m1block=MMulBlock(path=cluster_path / "M1"),
        ublock=UBlock(path=cluster_path / "U"),
        cblock=CBlock(path=cluster_path / "C"),
        iblock=IBlock(path=cluster_path / "I"),
        shblock=SHBlock(path=cluster_path / "SH"),
    )
    return Carrier(
        path=carrier_path,
        location=Loc.new_carrier(0, location_carrier),
        clusters=[cluster],
        tblock=None,
    )


def _make_wiring_spec(src_mac: str, src_pin, dst_mac: str, dst_pin) -> WiringSpec:
    return WiringSpec(
        source_entity_path=f"/{src_mac}",
        source_pin=src_pin,
        target_entity_path=f"/{dst_mac}",
        target_pin=dst_pin,
    )


class TestWiringSpecSerialization:

    def test_single_wire_emits_one_item_with_empty_entity_path(self):
        src_mac = "04-E9-E5-12-34-56"
        dst_mac = "04-E9-E5-12-34-57"
        carrier = _make_lucidac_carrier(src_mac)
        computer = LUCIStack(entities=[carrier])
        computer.wiring_specs.append(_make_wiring_spec(src_mac, 4, dst_mac, 4))

        module = LUCIDACSerializer().serialize(computer, skip_validation=True)
        wire_items = [it for it in module.items if it.WhichOneof("kind") == "wiring_specification"]

        assert len(wire_items) == 1
        item = wire_items[0]
        assert item.entity.path == ""
        ws = item.wiring_specification
        assert ws.source.entity.path == f"/{src_mac}"
        assert ws.source.WhichOneof("kind") == "indexed_pin"
        assert ws.source.indexed_pin == 4
        assert ws.target.entity.path == f"/{dst_mac}"
        assert ws.target.WhichOneof("kind") == "indexed_pin"
        assert ws.target.indexed_pin == 4


class TestWiringSpecDeserialization:

    def test_wire_item_populates_computer_wiring_specs(self):
        src_mac = "04-E9-E5-12-34-56"
        dst_mac = "04-E9-E5-12-34-57"

        original = LUCIStack(entities=[_make_lucidac_carrier(src_mac)])
        module = LUCIDACSerializer().serialize(original, skip_validation=True)

        wire_item = pb.Item(entity=pb.EntityId(path=""))
        wire_item.wiring_specification.source.entity.path = f"/{src_mac}"
        wire_item.wiring_specification.source.indexed_pin = 4
        wire_item.wiring_specification.target.entity.path = f"/{dst_mac}"
        wire_item.wiring_specification.target.indexed_pin = 4
        module.items.append(wire_item)

        reconstructed = LUCIStack(entities=[_make_lucidac_carrier(src_mac)])
        LUCIDACDeserializer(reconstructed).deserialize(module)

        assert len(reconstructed.wiring_specs) == 1
        ws = reconstructed.wiring_specs[0]
        assert ws.source_entity_path == f"/{src_mac}"
        assert ws.source_pin == 4
        assert ws.target_entity_path == f"/{dst_mac}"
        assert ws.target_pin == 4


class TestWiringSpecRoundTrip:

    def test_full_round_trip_preserves_wires(self):
        mac0 = "04-E9-E5-12-34-56"
        mac1 = "04-E9-E5-12-34-57"
        c0 = _make_lucidac_carrier(mac0, location_carrier=0)
        c1 = _make_lucidac_carrier(mac1, location_carrier=1)
        computer = LUCIStack(entities=[c0, c1])
        expected = [
            _make_wiring_spec(mac0, 4, mac1, 4),
            _make_wiring_spec(mac0, 5, mac1, 5),
            _make_wiring_spec(mac1, 4, mac0, 4),
        ]
        computer.wiring_specs.extend(expected)

        module = LUCIDACSerializer().serialize(computer, skip_validation=True)

        reconstructed = LUCIStack(entities=[
            _make_lucidac_carrier(mac0, location_carrier=0),
            _make_lucidac_carrier(mac1, location_carrier=1),
        ])
        LUCIDACDeserializer(reconstructed).deserialize(module)

        assert reconstructed.wiring_specs == expected

    def test_named_to_indexed_intra_entity_round_trip(self):
        mac = "04-E9-E5-12-34-56"
        carrier = _make_lucidac_carrier(mac, location_carrier=0)
        computer = LUCIStack(entities=[carrier])
        expected = WiringSpec(
            source_entity_path=f"/{mac}",
            source_pin="aux0",
            target_entity_path=f"/{mac}",
            target_pin=3,
        )
        computer.wiring_specs.append(expected)

        module = LUCIDACSerializer().serialize(computer, skip_validation=True)

        reconstructed = LUCIStack(entities=[_make_lucidac_carrier(mac, location_carrier=0)])
        LUCIDACDeserializer(reconstructed).deserialize(module)

        assert reconstructed.wiring_specs == [expected]

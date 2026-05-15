# Copyright (c) 2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import os

import pytest
from google.protobuf.json_format import MessageToDict

from pybrid.base.proto import main_pb2 as pb
from pybrid.base.proto.io import ProtoIO
from pybrid.redac.blocks.cblock import CBlock
from pybrid.redac.blocks.iblock import IBlock
from pybrid.redac.blocks.mblock import MBlock, MIntBlock, MMulBlock
from pybrid.redac.blocks.shblock import SHBlock
from pybrid.redac.blocks.ublock import UBlock
from pybrid.redac.carrier import Carrier
from pybrid.redac.cluster import Cluster
from pybrid.redac.device import Device
from pybrid.redac.entities import EntityClass, EntityType, Loc, Path, UnknownEntityTypeError

# Test fixture paths — these are frozen copies of device descriptions,
# independent of the live examples/ directory which tracks real hardware.
_FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
_REDAC_APB = os.path.join(_FIXTURES_DIR, "redac.apb")


def _read_apb_carrier_entities(apb_path: str) -> list:
    """Read carrier ``pb.Entity`` objects from an ``.apb`` file.

    Uses :meth:`ProtoIO.load_module` to load the module, then extracts
    entities from ``module.items[].entity_specification.entity``.

    :raises FileNotFoundError: If *apb_path* does not exist.
    :raises ValueError: If no carrier entities can be extracted.
    """
    pb_module = ProtoIO.load_module(apb_path)
    entities = [cfg.entity_specification.entity for cfg in pb_module.items if cfg.HasField("entity_specification")]
    if not entities:
        raise ValueError(f"No entity_specification entries found in {apb_path}")
    return entities


class TestEntityTypeReverseLookup:

    def test_reverse_lookup_ublock(self):
        result = EntityType.reverse_lookup(UBlock)
        assert result == EntityType(class_=EntityClass.UBLOCK, type_=None, version=None, variant=None)

    def test_reverse_lookup_cblock(self):
        result = EntityType.reverse_lookup(CBlock)
        assert result == EntityType(class_=EntityClass.CBLOCK, type_=None, version=None, variant=None)

    def test_reverse_lookup_iblock(self):
        result = EntityType.reverse_lookup(IBlock)
        assert result == EntityType(class_=EntityClass.IBLOCK, type_=None, version=None, variant=None)

    def test_reverse_lookup_unregistered_raises(self):
        class _UnregisteredClass:
            pass

        with pytest.raises(UnknownEntityTypeError):
            EntityType.reverse_lookup(_UnregisteredClass)

    def test_reverse_lookup_builtin_raises(self):
        with pytest.raises(UnknownEntityTypeError):
            EntityType.reverse_lookup(object)


class TestREDACDescriptionDeserializer:
    """Tests for REDACDeserializer specification deserialization from .apb files."""

    @pytest.fixture(scope="class")
    def carrier_entities(self):
        """Load carrier pb.Entity objects from the redac-tobias.apb file."""
        return _read_apb_carrier_entities(_REDAC_APB)

    @pytest.fixture(scope="class")
    def deserializer(self):
        from pybrid.redac.protocol.serializer import REDACDeserializer

        return REDACDeserializer()

    def test_deserializer_import(self):
        from pybrid.redac.protocol.serializer import REDACDeserializer

    def test_deserialize_carrier_returns_carrier(self, deserializer, carrier_entities):
        entity = carrier_entities[0]
        path = Path.parse(entity.id)
        result = deserializer.deserialize_specification(entity, path)
        assert isinstance(result, Carrier)

    def test_deserialize_all_seven_carriers(self, deserializer, carrier_entities):
        assert len(carrier_entities) == 7
        for entity in carrier_entities:
            path = Path.parse(entity.id)
            carrier = deserializer.deserialize_specification(entity, path)
            assert isinstance(carrier, Carrier)

    def test_carrier_has_three_clusters(self, deserializer, carrier_entities):
        for entity in carrier_entities:
            path = Path.parse(entity.id)
            carrier = deserializer.deserialize_specification(entity, path)
            assert len(carrier.clusters) == 3

    def test_carrier_path_matches_mac(self, deserializer, carrier_entities):
        # Each carrier entity id is e.g. "/04-E9-E5-17-E5-4F"
        for entity in carrier_entities:
            expected_mac = entity.id.lstrip("/")
            path = Path.parse(entity.id)
            carrier = deserializer.deserialize_specification(entity, path)
            assert str(carrier.path) == expected_mac

    def test_clusters_numbered_correctly(self, deserializer, carrier_entities):
        entity = carrier_entities[0]
        path = Path.parse(entity.id)
        carrier = deserializer.deserialize_specification(entity, path)
        mac = entity.id.lstrip("/")
        for idx, cluster in enumerate(carrier.clusters):
            assert str(cluster.path) == f"{mac}/{idx}"

    def test_cluster_has_required_blocks(self, deserializer, carrier_entities):
        entity = carrier_entities[0]
        path = Path.parse(entity.id)
        carrier = deserializer.deserialize_specification(entity, path)
        cluster = carrier.clusters[0]
        assert isinstance(cluster, Cluster)
        assert isinstance(cluster.ublock, UBlock)
        assert isinstance(cluster.cblock, CBlock)
        assert isinstance(cluster.iblock, IBlock)
        # shblock must be present
        assert cluster.shblock is not None

    def test_m0block_is_mint_type1(self, deserializer, carrier_entities):
        # All carriers except carrier 1/cluster 1 have M0 with type=1 (MIntBlock)
        entity = carrier_entities[0]
        path = Path.parse(entity.id)
        carrier = deserializer.deserialize_specification(entity, path)
        cluster = carrier.clusters[0]
        assert isinstance(cluster.m0block, MIntBlock)

    def test_m1block_is_mmul_type2(self, deserializer, carrier_entities):
        # All clusters across all carriers have M1 with type=2 (MMulBlock)
        for entity in carrier_entities:
            path = Path.parse(entity.id)
            carrier = deserializer.deserialize_specification(entity, path)
            for cluster in carrier.clusters:
                assert isinstance(cluster.m1block, MMulBlock)

    def test_carrier1_cluster1_m0block_is_mint(self, deserializer, carrier_entities):
        entity = carrier_entities[1]
        assert entity.id == "/04-E9-E5-1B-C4-DA"
        path = Path.parse(entity.id)
        carrier = deserializer.deserialize_specification(entity, path)
        assert isinstance(carrier.clusters[1].m0block, MIntBlock)

    def test_carrier_with_tblock(self, deserializer, carrier_entities):
        # Carrier 0 has both T block and backplane (ST0, ST1, ST2)
        entity = carrier_entities[0]
        path = Path.parse(entity.id)
        carrier = deserializer.deserialize_specification(entity, path)
        assert carrier.tblock is not None
        assert carrier.st0block is not None
        assert carrier.st1block is not None
        assert carrier.st2block is not None

    def test_carrier_location_from_v0(self, deserializer, carrier_entities):
        # All carriers in this file have v0 location data
        for entity in carrier_entities:
            path = Path.parse(entity.id)
            carrier = deserializer.deserialize_specification(entity, path)
            assert carrier.location is not None

    def test_deserialize_device_entity(self, deserializer, carrier_entities):
        # Build a device-level pb.Entity (class=DEVICE) wrapping all carriers and
        # verify we get back a Device with all carriers.
        first_mac = carrier_entities[0].id
        device_entity = pb.Entity(id=first_mac, class_=pb.Entity.DEVICE)
        for ce in carrier_entities:
            device_entity.children.append(ce)

        root_path = Path.parse(first_mac)
        result = deserializer.deserialize_specification(device_entity, root_path)
        assert isinstance(result, Device)
        assert len(result.carriers) == 7

    def test_deserialize_device_carriers_are_carrier_instances(self, deserializer, carrier_entities):
        first_mac = carrier_entities[0].id
        device_entity = pb.Entity(id=first_mac, class_=pb.Entity.DEVICE)
        for ce in carrier_entities:
            device_entity.children.append(ce)

        root_path = Path.parse(first_mac)
        device = deserializer.deserialize_specification(device_entity, root_path)
        for carrier in device.carriers:
            assert isinstance(carrier, Carrier)
            assert len(carrier.clusters) == 3


def _pb_entity_to_class_type_map(entity: pb.Entity) -> dict:
    """Recursively build a map of entity id → (class_, type) for structural comparison."""
    result = {entity.id: (entity.class_, entity.type)}
    for child in entity.children:
        result.update(_pb_entity_to_class_type_map(child))
    return result


def _pb_entity_child_ids(entity: pb.Entity) -> list:
    """Return sorted list of direct child ids."""
    return sorted(ch.id for ch in entity.children)


class TestREDACDescriptionSerializer:

    @pytest.fixture(scope="class")
    def deserializer(self):
        from pybrid.redac.protocol.serializer import REDACDeserializer

        return REDACDeserializer()

    @pytest.fixture(scope="class")
    def serializer(self):
        from pybrid.redac.protocol.serializer import REDACSerializer

        return REDACSerializer()

    @pytest.fixture(scope="class")
    def apb_carrier_entities(self):
        return _read_apb_carrier_entities(_REDAC_APB)

    def test_serializer_import(self):
        from pybrid.redac.protocol.serializer import REDACSerializer

    def test_apb_carrier_roundtrip_class_and_type(self, deserializer, serializer, apb_carrier_entities):
        # Each carrier in the .apb file should roundtrip with the same class_ and type.
        for entity in apb_carrier_entities:
            path = Path.parse(entity.id)
            carrier = deserializer.deserialize_specification(entity, path)
            result = serializer.serialize_specification(carrier)
            assert result.class_ == entity.class_
            assert result.type == entity.type

    def test_apb_carrier_roundtrip_id(self, deserializer, serializer, apb_carrier_entities):
        # The serialized entity id must match the original carrier id (MAC address).
        for entity in apb_carrier_entities:
            path = Path.parse(entity.id)
            carrier = deserializer.deserialize_specification(entity, path)
            result = serializer.serialize_specification(carrier)
            assert result.id == entity.id

    def test_apb_carrier_roundtrip_cluster_count(self, deserializer, serializer, apb_carrier_entities):
        # Each serialized carrier must have the same number of cluster children.
        for entity in apb_carrier_entities:
            path = Path.parse(entity.id)
            carrier = deserializer.deserialize_specification(entity, path)
            result = serializer.serialize_specification(carrier)
            original_cluster_ids = {ch.id for ch in entity.children if ch.id.lstrip("/").isdigit()}
            result_cluster_ids = {ch.id for ch in result.children if ch.id.lstrip("/").isdigit()}
            assert result_cluster_ids == original_cluster_ids

    def test_apb_carrier_roundtrip_block_class_and_type(self, deserializer, serializer, apb_carrier_entities):
        # Block class_ and type fields inside each cluster must survive the roundtrip.
        for entity in apb_carrier_entities:
            path = Path.parse(entity.id)
            carrier = deserializer.deserialize_specification(entity, path)
            result = serializer.serialize_specification(carrier)

            original_map = _pb_entity_to_class_type_map(entity)
            result_map = _pb_entity_to_class_type_map(result)

            # Every block id present in the result must match original class/type.
            for block_id, class_type in result_map.items():
                if block_id in original_map:
                    assert (
                        class_type == original_map[block_id]
                    ), f"Block {block_id}: expected {original_map[block_id]}, got {class_type}"

    def test_apb_carrier_roundtrip_tblock_present(self, deserializer, serializer, apb_carrier_entities):
        # Carriers that had a T-block in the original must have one after roundtrip.
        for entity in apb_carrier_entities:
            original_has_tblock = any(ch.id in ("/T", "T") for ch in entity.children)
            if not original_has_tblock:
                continue
            path = Path.parse(entity.id)
            carrier = deserializer.deserialize_specification(entity, path)
            result = serializer.serialize_specification(carrier)
            result_has_tblock = any(ch.id in ("/T", "T") for ch in result.children)
            assert result_has_tblock, f"T-block missing from serialized carrier {entity.id}"

    def test_apb_device_roundtrip_carrier_count(self, deserializer, serializer, apb_carrier_entities):
        # Build a synthetic DEVICE entity, roundtrip it, and verify all 7 carriers are present.
        first_mac = apb_carrier_entities[0].id
        device_entity = pb.Entity(id=first_mac, class_=pb.Entity.DEVICE)
        for ce in apb_carrier_entities:
            device_entity.children.append(ce)

        root_path = Path.parse(first_mac)
        device = deserializer.deserialize_specification(device_entity, root_path)

        result = serializer.serialize_specification(device)

        assert result.class_ == pb.Entity.DEVICE
        assert len(result.children) == len(apb_carrier_entities)

    def test_apb_device_roundtrip_carrier_ids(self, deserializer, serializer, apb_carrier_entities):
        # All carrier MAC IDs must be preserved after device-level roundtrip.
        first_mac = apb_carrier_entities[0].id
        device_entity = pb.Entity(id=first_mac, class_=pb.Entity.DEVICE)
        for ce in apb_carrier_entities:
            device_entity.children.append(ce)

        root_path = Path.parse(first_mac)
        device = deserializer.deserialize_specification(device_entity, root_path)
        result = serializer.serialize_specification(device)

        original_carrier_ids = {ce.id for ce in apb_carrier_entities}
        result_carrier_ids = {ch.id for ch in result.children}
        assert result_carrier_ids == original_carrier_ids

    def test_dummydac_roundtrip_carrier_count(self, deserializer, serializer):
        # The DummyDAC entity tree must survive a full roundtrip with the same carrier count.
        from pybrid.mock.config import DummyDACConfig
        from pybrid.mock.dummy_dac import DummyDAC

        dac = DummyDAC("127.0.0.1", 5732, DummyDACConfig())
        root = dac._build_entity_tree()

        root_path = Path.parse(root.id)
        device = deserializer.deserialize_specification(root, root_path)
        result = serializer.serialize_specification(device)

        assert result.class_ == pb.Entity.DEVICE
        assert len(result.children) == len(root.children)

    def test_dummydac_roundtrip_carrier_ids(self, deserializer, serializer):
        # Carrier IDs must be preserved after DummyDAC roundtrip.
        from pybrid.mock.config import DummyDACConfig
        from pybrid.mock.dummy_dac import DummyDAC

        dac = DummyDAC("127.0.0.1", 5732, DummyDACConfig())
        root = dac._build_entity_tree()

        root_path = Path.parse(root.id)
        device = deserializer.deserialize_specification(root, root_path)
        result = serializer.serialize_specification(device)

        original_carrier_ids = {ch.id for ch in root.children}
        result_carrier_ids = {ch.id for ch in result.children}
        assert result_carrier_ids == original_carrier_ids

    def test_dummydac_roundtrip_block_class_and_type(self, deserializer, serializer):
        # Block class_ and type fields inside each DummyDAC carrier must survive the roundtrip.
        from pybrid.mock.config import DummyDACConfig
        from pybrid.mock.dummy_dac import DummyDAC

        dac = DummyDAC("127.0.0.1", 5732, DummyDACConfig())
        root = dac._build_entity_tree()

        for carrier_entity in root.children:
            carrier_path = Path.parse(carrier_entity.id)
            carrier = deserializer.deserialize_specification(carrier_entity, carrier_path)
            result = serializer.serialize_specification(carrier)

            original_map = _pb_entity_to_class_type_map(carrier_entity)
            result_map = _pb_entity_to_class_type_map(result)

            for block_id, class_type in result_map.items():
                if block_id in original_map:
                    assert (
                        class_type == original_map[block_id]
                    ), f"Block {block_id}: expected {original_map[block_id]}, got {class_type}"

    def test_dummydac_roundtrip_tblock_present(self, deserializer, serializer):
        # DummyDAC carriers include a T-block; it must appear after roundtrip.
        from pybrid.mock.config import DummyDACConfig
        from pybrid.mock.dummy_dac import DummyDAC

        dac = DummyDAC("127.0.0.1", 5732, DummyDACConfig())
        root = dac._build_entity_tree()

        for carrier_entity in root.children:
            carrier_path = Path.parse(carrier_entity.id)
            carrier = deserializer.deserialize_specification(carrier_entity, carrier_path)
            result = serializer.serialize_specification(carrier)
            result_has_tblock = any(ch.id in ("/T", "T") for ch in result.children)
            assert result_has_tblock, f"T-block missing from serialized carrier {carrier_entity.id}"

    def test_serialize_returns_pb_entity(self, deserializer, serializer, apb_carrier_entities):
        # The return value of serialize_specification() must always be a pb.Entity instance.
        entity = apb_carrier_entities[0]
        path = Path.parse(entity.id)
        carrier = deserializer.deserialize_specification(entity, path)
        result = serializer.serialize_specification(carrier)
        assert isinstance(result, pb.Entity)


# Absolute path to the LUCIDAC device description file, relative to the repo root.
_LUCIDAC_APB = os.path.join(_FIXTURES_DIR, "lucidac.apb")


class TestLUCIDACDescriptionDeserializer:

    @pytest.fixture(scope="class")
    def deserializer(self):
        from pybrid.lucidac.protocol.serializer import LUCIDACDeserializer

        return LUCIDACDeserializer()

    @pytest.fixture(scope="class")
    def lucidac_carrier_entity(self):
        return _read_apb_carrier_entities(_LUCIDAC_APB)[0]

    def test_deserializer_import(self):
        from pybrid.lucidac.protocol.serializer import LUCIDACDeserializer

    def test_deserialize_carrier_returns_carrier(self, deserializer, lucidac_carrier_entity):
        path = Path.parse(lucidac_carrier_entity.id)
        result = deserializer.deserialize_specification(lucidac_carrier_entity, path)
        assert isinstance(result, Carrier)

    def test_front_plane_is_present(self, deserializer, lucidac_carrier_entity):
        # LUCIDACDeserializer must recognize the /FP child and
        # populate carrier.front_plane (not leave it as None like the REDAC base does).
        path = Path.parse(lucidac_carrier_entity.id)
        carrier = deserializer.deserialize_specification(lucidac_carrier_entity, path)
        assert carrier.front_plane is not None

    def test_front_plane_type(self, deserializer, lucidac_carrier_entity):
        from pybrid.lucidac.front_plane import FrontPlane

        path = Path.parse(lucidac_carrier_entity.id)
        carrier = deserializer.deserialize_specification(lucidac_carrier_entity, path)
        assert isinstance(carrier.front_plane, FrontPlane)

    def test_carrier_has_one_cluster(self, deserializer, lucidac_carrier_entity):
        path = Path.parse(lucidac_carrier_entity.id)
        carrier = deserializer.deserialize_specification(lucidac_carrier_entity, path)
        assert len(carrier.clusters) == 1

    def test_cluster_has_all_blocks(self, deserializer, lucidac_carrier_entity):
        path = Path.parse(lucidac_carrier_entity.id)
        carrier = deserializer.deserialize_specification(lucidac_carrier_entity, path)
        cluster = carrier.clusters[0]
        assert isinstance(cluster, Cluster)
        assert isinstance(cluster.ublock, UBlock)
        assert isinstance(cluster.cblock, CBlock)
        assert isinstance(cluster.iblock, IBlock)

    def test_redac_base_deserializer_skips_fp(self, lucidac_carrier_entity):
        # The base REDACDeserializer must NOT set front_plane on the carrier
        # when encountering an /FP child (it only logs a warning).
        from pybrid.redac.protocol.serializer import REDACDeserializer

        base_deserializer = REDACDeserializer()
        path = Path.parse(lucidac_carrier_entity.id)
        carrier = base_deserializer.deserialize_specification(lucidac_carrier_entity, path)
        assert carrier.front_plane is None

    def test_acl_select_populated(self, deserializer, lucidac_carrier_entity):
        # After deserializing a LUCIDAC carrier with FP, acl_select must be set.
        path = Path.parse(lucidac_carrier_entity.id)
        carrier = deserializer.deserialize_specification(lucidac_carrier_entity, path)
        assert carrier.acl_select is not None
        assert len(carrier.acl_select) == 8


class TestLUCIDACDescriptionSerializer:

    @pytest.fixture(scope="class")
    def deserializer(self):
        from pybrid.lucidac.protocol.serializer import LUCIDACDeserializer

        return LUCIDACDeserializer()

    @pytest.fixture(scope="class")
    def serializer(self):
        from pybrid.lucidac.protocol.serializer import LUCIDACSerializer

        return LUCIDACSerializer()

    @pytest.fixture(scope="class")
    def lucidac_carrier_entity(self):
        return _read_apb_carrier_entities(_LUCIDAC_APB)[0]

    def test_serializer_import(self):
        from pybrid.lucidac.protocol.serializer import LUCIDACSerializer

    def test_lucidac_roundtrip_carrier_id(self, deserializer, serializer, lucidac_carrier_entity):
        path = Path.parse(lucidac_carrier_entity.id)
        carrier = deserializer.deserialize_specification(lucidac_carrier_entity, path)
        result = serializer.serialize_specification(carrier)
        assert result.id == lucidac_carrier_entity.id

    def test_lucidac_roundtrip_carrier_class_and_type(self, deserializer, serializer, lucidac_carrier_entity):
        path = Path.parse(lucidac_carrier_entity.id)
        carrier = deserializer.deserialize_specification(lucidac_carrier_entity, path)
        result = serializer.serialize_specification(carrier)
        assert result.class_ == lucidac_carrier_entity.class_
        assert result.type == lucidac_carrier_entity.type

    def test_lucidac_roundtrip_fp_child_present(self, deserializer, serializer, lucidac_carrier_entity):
        # After roundtrip, the serialized carrier entity must have an /FP child.
        path = Path.parse(lucidac_carrier_entity.id)
        carrier = deserializer.deserialize_specification(lucidac_carrier_entity, path)
        result = serializer.serialize_specification(carrier)
        child_ids = [ch.id for ch in result.children]
        assert "/FP" in child_ids

    def test_lucidac_roundtrip_cluster_count(self, deserializer, serializer, lucidac_carrier_entity):
        path = Path.parse(lucidac_carrier_entity.id)
        carrier = deserializer.deserialize_specification(lucidac_carrier_entity, path)
        result = serializer.serialize_specification(carrier)
        cluster_children = [ch for ch in result.children if ch.class_ == pb.Entity.CLUSTER]
        assert len(cluster_children) == 1

    def test_lucidac_roundtrip_returns_pb_entity(self, deserializer, serializer, lucidac_carrier_entity):
        path = Path.parse(lucidac_carrier_entity.id)
        carrier = deserializer.deserialize_specification(lucidac_carrier_entity, path)
        result = serializer.serialize_specification(carrier)
        assert isinstance(result, pb.Entity)

    def test_description_vs_configuration_independence(self):
        # Description (structural) serialization must be unaffected by changes to
        # configuration state (CBlock coefficients, UBlock connections).
        from pybrid.base.utils.addressing import AddressingMap
        from pybrid.lucidac.computer import LUCIDAC
        from pybrid.lucidac.protocol.serializer import LUCIDACDeserializer, LUCIDACSerializer
        from pybrid.redac.blocks import CBlock, MIntBlock, UBlock
        from pybrid.redac.carrier import Carrier
        from pybrid.redac.cluster import Cluster
        from pybrid.redac.entities import Path

        mac = AddressingMap.map_redac(0)
        carrier_path = Path.parse(mac)
        cluster_path = carrier_path / "0"
        cluster = Cluster(
            path=cluster_path,
            location=Loc.new_cluster(0, 0, 0),
            m0block=MIntBlock(path=cluster_path / "M0"),
            ublock=UBlock(path=cluster_path / "U"),
            cblock=CBlock(path=cluster_path / "C"),
            iblock=IBlock(path=cluster_path / "I"),
            shblock=None,
        )
        carrier = Carrier(path=carrier_path, location=Loc.new_carrier(0, 0), clusters=[cluster], tblock=None)
        computer = LUCIDAC(entities=[carrier])

        desc_ser = LUCIDACSerializer()

        # Capture description before any configuration changes.
        desc_before = MessageToDict(
            desc_ser.serialize_specification(computer.carriers[0]),
            preserving_proto_field_name=True,
        )

        # Modify configuration state: CBlock coefficients and UBlock connections.
        cluster.cblock.elements[0].computation.factor = 0.5
        cluster.cblock.elements[1].computation.factor = -0.25
        cluster.ublock.outputs[0] = 5
        cluster.ublock.outputs[10] = 3

        # Capture description after configuration changes.
        desc_after = MessageToDict(
            desc_ser.serialize_specification(computer.carriers[0]),
            preserving_proto_field_name=True,
        )

        # Structural description must be identical before and after config changes.
        assert desc_before == desc_after

        # Verify configuration serialization does reflect the changes.
        config_ser_cls = computer.get_serializer()
        config_ser = config_ser_cls()
        module = config_ser.serialize(computer)

        # At least one config entry must be present (UBlock or CBlock config).
        assert len(module.items) > 0

# Copyright (c) 2022-2025 anabrid GmbH
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import pytest

from pybrid.base.hybrid.serializer import Serializer, Deserializer
from pybrid.base.proto import main_pb2 as pb
from pybrid.redac.carrier import Carrier
from pybrid.redac.cluster import Cluster
from pybrid.redac.blocks import UBlock, CBlock, IBlock, MIntBlock
from pybrid.redac.entities import Path
from pybrid.base.utils.addressing import AddressingMap

from tests.integration.test_serialization import (
    make_test_lucidac,
    make_test_redac_with_mblock,
)


def _make_lucidac_with_config():
    """Create a LUCIDAC with non-default configuration in all relevant blocks."""
    computer = make_test_lucidac()
    cluster = computer.carriers[0].clusters[0]

    cluster.cblock.elements[0].computation.factor = 0.5
    cluster.cblock.elements[1].computation.factor = -0.25
    cluster.ublock.outputs[0] = 5
    cluster.ublock.outputs[10] = 3
    cluster.iblock.outputs[0] = {0, 1}
    cluster.iblock.upscaling[0] = True
    cluster.m0block.elements[0].ic = 0.5
    cluster.m0block.elements[0].k = 100

    return computer


class TestFullBundleRoundtrip:
    """Serialize spec+config via the base Serializer.serialize(), then deserialize back
    and verify entity structure and configuration state are preserved."""

    def test_full_module_contains_spec_and_config_entries(self):
        computer = _make_lucidac_with_config()
        serializer = computer.get_serializer()()

        module = Serializer.serialize(serializer, computer)

        spec_entries = [c for c in module.items if c.WhichOneof('kind') == 'entity_specification']
        config_entries = [c for c in module.items if c.WhichOneof('kind') != 'entity_specification']

        assert len(spec_entries) > 0, "Full module must include entity_specification (spec) entries"
        assert len(config_entries) > 0, "Full module must include operational config entries"

    def test_full_module_spec_paths_match_entities(self):
        computer = _make_lucidac_with_config()
        serializer = computer.get_serializer()()

        module = Serializer.serialize(serializer, computer)
        spec_entries = [c for c in module.items if c.WhichOneof('kind') == 'entity_specification']

        # Each computer.entities entry should produce one spec entry
        entity_paths = {str(e.path) for e in computer.entities}
        spec_paths = {c.entity.path for c in spec_entries}
        assert entity_paths == spec_paths

    def test_roundtrip_cblock_factors_preserved(self):
        computer = _make_lucidac_with_config()
        serializer = computer.get_serializer()()
        deserializer_cls = computer.get_deserializer()

        # Produce full module (spec + config)
        module = Serializer.serialize(serializer, computer)

        # Separate spec from config entries
        spec_entries = [c for c in module.items if c.WhichOneof('kind') == 'entity_specification']
        config_entries = [c for c in module.items if c.WhichOneof('kind') != 'entity_specification']

        # Rebuild entity tree from spec entries
        deser = deserializer_cls()
        restored_carriers = []
        for spec_conf in spec_entries:
            entity = spec_conf.entity_specification.entity
            path = Path.parse(spec_conf.entity.path)
            restored_carriers.append(deser.deserialize_specification(entity, path))

        # Create a fresh computer with the rebuilt structure
        from pybrid.lucidac.computer import LUCIDAC
        fresh_computer = LUCIDAC(entities=restored_carriers)

        # Apply configuration onto the fresh computer
        deser.computer = fresh_computer
        deser.deserialize_configuration(config_entries)

        orig_cluster = computer.carriers[0].clusters[0]
        rest_cluster = fresh_computer.carriers[0].clusters[0]

        assert rest_cluster.cblock.elements[0].computation.factor == pytest.approx(
            orig_cluster.cblock.elements[0].computation.factor, rel=1e-6
        )
        assert rest_cluster.cblock.elements[1].computation.factor == pytest.approx(
            orig_cluster.cblock.elements[1].computation.factor, rel=1e-6
        )

    def test_roundtrip_iblock_connections_preserved(self):
        computer = _make_lucidac_with_config()
        serializer = computer.get_serializer()()
        deserializer_cls = computer.get_deserializer()

        module = Serializer.serialize(serializer, computer)
        spec_entries = [c for c in module.items if c.WhichOneof('kind') == 'entity_specification']
        config_entries = [c for c in module.items if c.WhichOneof('kind') != 'entity_specification']

        deser = deserializer_cls()
        restored_carriers = [
            deser.deserialize_specification(
                c.entity_specification.entity, Path.parse(c.entity.path)
            )
            for c in spec_entries
        ]

        from pybrid.lucidac.computer import LUCIDAC
        fresh_computer = LUCIDAC(entities=restored_carriers)
        deser.computer = fresh_computer
        deser.deserialize_configuration(config_entries)

        orig_cluster = computer.carriers[0].clusters[0]
        rest_cluster = fresh_computer.carriers[0].clusters[0]

        assert rest_cluster.iblock.outputs[0] == orig_cluster.iblock.outputs[0]
        assert rest_cluster.iblock.upscaling[0] == orig_cluster.iblock.upscaling[0]

    def test_roundtrip_entity_structure_preserved(self):
        computer = _make_lucidac_with_config()
        serializer = computer.get_serializer()()
        deserializer_cls = computer.get_deserializer()

        module = Serializer.serialize(serializer, computer)
        spec_entries = [c for c in module.items if c.WhichOneof('kind') == 'entity_specification']

        deser = deserializer_cls()
        restored_carriers = [
            deser.deserialize_specification(
                c.entity_specification.entity, Path.parse(c.entity.path)
            )
            for c in spec_entries
        ]

        from pybrid.lucidac.computer import LUCIDAC
        fresh_computer = LUCIDAC(entities=restored_carriers)

        assert len(fresh_computer.carriers) == len(computer.carriers)
        assert len(fresh_computer.carriers[0].clusters) == len(computer.carriers[0].clusters)
        for i, (orig_c, rest_c) in enumerate(zip(computer.carriers, fresh_computer.carriers)):
            assert str(orig_c.path) == str(rest_c.path), f"Carrier {i} path mismatch"


class TestSpecificationOnlyIndependence:
    """serialize_specification() must not be affected by configuration state changes."""

    def test_spec_unchanged_after_cblock_config_change(self):
        computer = make_test_lucidac()
        serializer = computer.get_serializer()()
        from google.protobuf.json_format import MessageToDict

        before = MessageToDict(
            serializer.serialize_specification(computer.carriers[0]),
            preserving_proto_field_name=True,
        )

        computer.carriers[0].clusters[0].cblock.elements[0].computation.factor = 0.42
        computer.carriers[0].clusters[0].cblock.elements[5].computation.factor = -0.99
        computer.carriers[0].clusters[0].ublock.outputs[3] = 7

        after = MessageToDict(
            serializer.serialize_specification(computer.carriers[0]),
            preserving_proto_field_name=True,
        )

        assert before == after, "Specification serialization must be identical before and after config changes"

    def test_spec_unchanged_after_iblock_config_change(self):
        computer = make_test_lucidac()
        serializer = computer.get_serializer()()
        from google.protobuf.json_format import MessageToDict

        before = MessageToDict(
            serializer.serialize_specification(computer.carriers[0]),
            preserving_proto_field_name=True,
        )

        computer.carriers[0].clusters[0].iblock.outputs[0] = {0, 1, 2}
        computer.carriers[0].clusters[0].iblock.upscaling[0] = True

        after = MessageToDict(
            serializer.serialize_specification(computer.carriers[0]),
            preserving_proto_field_name=True,
        )

        assert before == after

    def test_config_serialization_reflects_changes(self):
        computer = make_test_lucidac()
        serializer = computer.get_serializer()()

        computer.carriers[0].clusters[0].cblock.elements[0].computation.factor = 0.42
        computer.carriers[0].clusters[0].ublock.outputs[0] = 3

        configs = serializer.serialize_configuration(computer)
        assert len(configs) > 0, "Configuration serialization must produce entries after state changes"


class TestConfigurationOnlyDeserialize:
    """deserialize_configuration() applies operational config to an existing computer."""

    def test_cblock_factors_applied(self):
        computer = make_test_redac_with_mblock()
        cluster = computer.carriers[0].clusters[0]

        cluster.cblock.elements[0].computation.factor = 0.75
        cluster.cblock.elements[2].computation.factor = -0.33

        serializer = computer.get_serializer()()
        configs = serializer.serialize_configuration(computer)

        fresh_computer = make_test_redac_with_mblock()
        deser = computer.get_deserializer()(fresh_computer)
        deser.deserialize_configuration(configs)

        fresh_cluster = fresh_computer.carriers[0].clusters[0]
        assert fresh_cluster.cblock.elements[0].computation.factor == pytest.approx(0.75, rel=1e-6)
        assert fresh_cluster.cblock.elements[2].computation.factor == pytest.approx(-0.33, rel=1e-6)

    def test_ublock_connections_applied(self):
        computer = make_test_redac_with_mblock()
        cluster = computer.carriers[0].clusters[0]

        cluster.ublock.outputs[5] = 7
        cluster.ublock.outputs[20] = 14

        serializer = computer.get_serializer()()
        configs = serializer.serialize_configuration(computer)

        fresh_computer = make_test_redac_with_mblock()
        deser = computer.get_deserializer()(fresh_computer)
        deser.deserialize_configuration(configs)

        fresh_cluster = fresh_computer.carriers[0].clusters[0]
        assert fresh_cluster.ublock.outputs[5] == 7
        assert fresh_cluster.ublock.outputs[20] == 14

    def test_mintblock_ic_applied(self):
        computer = make_test_redac_with_mblock()
        cluster = computer.carriers[0].clusters[0]

        cluster.m0block.elements[0].ic = 0.8
        cluster.m0block.elements[0].k = 100

        serializer = computer.get_serializer()()
        configs = serializer.serialize_configuration(computer)

        fresh_computer = make_test_redac_with_mblock()
        deser = computer.get_deserializer()(fresh_computer)
        deser.deserialize_configuration(configs)

        fresh_cluster = fresh_computer.carriers[0].clusters[0]
        assert fresh_cluster.m0block.elements[0].ic == pytest.approx(0.8, rel=1e-6)
        assert fresh_cluster.m0block.elements[0].k == 100


class TestMixedBundleOrdering:
    """Deserializer.deserialize() must process spec entries first regardless of input order."""

    def _make_interleaved_module(self, computer):
        """Build a pb.Item list with spec and config entries interleaved."""
        serializer = computer.get_serializer()()
        module = Serializer.serialize(serializer, computer)

        spec_entries = [c for c in module.items if c.WhichOneof('kind') == 'entity_specification']
        config_entries = [c for c in module.items if c.WhichOneof('kind') != 'entity_specification']

        # Interleave: config, spec, config, spec, ...
        interleaved = []
        config_iter = iter(config_entries)
        spec_iter = iter(spec_entries)
        for spec in spec_iter:
            try:
                interleaved.append(next(config_iter))
            except StopIteration:
                pass
            interleaved.append(spec)
        interleaved.extend(config_iter)

        return interleaved, spec_entries, config_entries

    def test_deserialize_processes_spec_before_config(self):
        computer = _make_lucidac_with_config()
        interleaved, spec_entries, config_entries = self._make_interleaved_module(computer)

        # Verify interleaving is actually mixed
        kinds = [c.WhichOneof('kind') for c in interleaved]
        has_config_before_spec = any(
            kinds[i] != 'entity_specification' and kinds[j] == 'entity_specification'
            for i in range(len(kinds))
            for j in range(i + 1, len(kinds))
        )
        assert has_config_before_spec, "Test setup: module must actually be interleaved"

    def test_interleaved_module_correct_cblock_result(self):
        """Base Deserializer.deserialize() must handle interleaved order and produce correct config."""
        computer = _make_lucidac_with_config()
        interleaved, spec_entries, config_entries = self._make_interleaved_module(computer)

        # Rebuild spec separately (base deserialize discards spec return values)
        deserializer_cls = computer.get_deserializer()
        deser = deserializer_cls()
        restored_carriers = [
            deser.deserialize_specification(
                c.entity_specification.entity, Path.parse(c.entity.path)
            )
            for c in spec_entries
        ]
        from pybrid.lucidac.computer import LUCIDAC
        fresh_computer = LUCIDAC(entities=restored_carriers)
        deser.computer = fresh_computer

        # Now apply the base deserialize() on the interleaved module — it should sort spec first
        Deserializer.deserialize(deser, pb.Module(items=interleaved))

        orig_cluster = computer.carriers[0].clusters[0]
        rest_cluster = fresh_computer.carriers[0].clusters[0]

        assert rest_cluster.cblock.elements[0].computation.factor == pytest.approx(
            orig_cluster.cblock.elements[0].computation.factor, rel=1e-6
        )
        assert rest_cluster.iblock.outputs[0] == orig_cluster.iblock.outputs[0]

    def test_ordered_and_interleaved_produce_same_config_result(self):
        """Config deserialization outcome must be identical regardless of entry ordering."""
        computer = _make_lucidac_with_config()
        serializer = computer.get_serializer()()
        deserializer_cls = computer.get_deserializer()

        ordered_module = Serializer.serialize(serializer, computer)
        spec_entries = [c for c in ordered_module.items if c.WhichOneof('kind') == 'entity_specification']
        config_entries = [c for c in ordered_module.items if c.WhichOneof('kind') != 'entity_specification']

        def rebuild_from_spec(spec_entries):
            deser = deserializer_cls()
            carriers = [
                deser.deserialize_specification(
                    c.entity_specification.entity, Path.parse(c.entity.path)
                )
                for c in spec_entries
            ]
            from pybrid.lucidac.computer import LUCIDAC
            return LUCIDAC(entities=carriers), deser

        # Ordered: spec first, then config
        ordered_computer, deser1 = rebuild_from_spec(spec_entries)
        deser1.computer = ordered_computer
        deser1.deserialize_configuration(config_entries)

        # Interleaved: via base Deserializer.deserialize()
        interleaved_computer, deser2 = rebuild_from_spec(spec_entries)
        deser2.computer = interleaved_computer
        interleaved_items = list(reversed(spec_entries)) + config_entries
        Deserializer.deserialize(deser2, pb.Module(items=interleaved_items))

        for i in range(32):
            assert (
                ordered_computer.carriers[0].clusters[0].cblock.elements[i].computation.factor
                == pytest.approx(
                    interleaved_computer.carriers[0].clusters[0].cblock.elements[i].computation.factor,
                    rel=1e-6,
                )
            )

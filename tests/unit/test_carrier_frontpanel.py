# Copyright (c) 2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
Unit tests for FrontPlane integration on the Carrier level.

These tests verify that:
- REDACDeserializer correctly parses /FP children from the protobuf
  entity tree (as reported by LUCIDAC hardware).
- Carrier.children yields the FrontPlane when present.
- Carriers without a /FP child (e.g. REDAC simulator) have front_plane=None.
- LUCIStack exposes FrontPlane via carrier access (lucistack.entities[0].front_plane).
- Serialization via BFS traversal of Carrier children includes the
  FrontPlane configuration at the correct entity path.

Updated for FrontPanel -> FrontPlane rename, LUCIDAC -> LUCIStack.
"""

import pytest

import pybrid.base.proto.main_pb2 as pb
from pybrid.redac.carrier import Carrier
from pybrid.redac.cluster import Cluster
from pybrid.redac.blocks import UBlock, CBlock, IBlock, MIntBlock
from pybrid.redac.entities import Path, EntityClass
from pybrid.base.utils.addressing import AddressingMap
from pybrid.redac.protocol.serializer import REDACDeserializer

# Import new names with fallback to old names so tests fail (not crash)
try:
    from pybrid.lucidac.computer import LUCIStack
except ImportError:
    from pybrid.lucidac.computer import LUCIDAC as LUCIStack

try:
    from pybrid.lucidac.front_plane import FrontPlane
except ImportError:
    from pybrid.lucidac.front_panel import FrontPanel as FrontPlane


def _make_version(major: int = 1, minor: int = 0, patch: int = 0) -> pb.Version:
    """Create a protobuf Version message."""
    return pb.Version(major=major, minor=minor, patch=patch)


def _make_block_entity(block_id: str, class_val: int) -> pb.Entity:
    """Create a protobuf Entity for a function block (M0, U, C, I, SH, etc.)."""
    return pb.Entity(
        id=block_id,
        class_=class_val,
        type=1,
        variant=1,
        version=_make_version(),
        eui="00-00-00-00-00-00-00",
    )


def _make_cluster_entity(cluster_id: str = "0") -> pb.Entity:
    """
    Create a protobuf Entity for a cluster with the standard function blocks.

    Includes M0 (class=3), U (class=4), C (class=5), I (class=6), SH (class=7).
    """
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


def _make_fp_entity() -> pb.Entity:
    """
    Create a protobuf Entity for the FrontPlane as reported by LUCIDAC firmware.

    The firmware reports FP with class_=UNKNOWN (0), which is the key detail:
    detection must happen by entity name ("FP"), not by class value.
    """
    return pb.Entity(
        id="FP",
        class_=0,  # UNKNOWN -- firmware does not report FRONT_PANEL(8)
        type=0,
        variant=0,
        version=_make_version(),
        eui="00-00-00-00-00-00-00",
    )


def _make_tblock_entity() -> pb.Entity:
    """Create a protobuf Entity for the T-block."""
    return pb.Entity(
        id="T",
        class_=10,  # TBLOCK
        type=1,
        variant=1,
        version=_make_version(),
        eui="00-00-00-00-00-00-00",
    )


def _make_carrier_entity(mac: str, include_fp: bool = True) -> pb.Entity:
    """
    Build a complete carrier protobuf Entity tree.

    Args:
        mac: MAC address string for the carrier (e.g. "00-00-00-00-00-00").
        include_fp: If True, include a /FP child entity (LUCIDAC mode).
                     If False, omit it (REDAC simulator mode).

    Returns:
        A protobuf Entity with class=CARRIER, containing cluster(s), T-block,
        and optionally a FrontPlane child.
    """
    carrier = pb.Entity(
        id=mac,
        class_=1,  # CARRIER
        type=1,
        variant=1,
        version=_make_version(),
        eui="00-00-00-00-00-00-00",
    )
    carrier.children.append(_make_cluster_entity("0"))
    carrier.children.append(_make_tblock_entity())
    if include_fp:
        carrier.children.append(_make_fp_entity())
    return carrier


def _make_minimal_carrier(mac: str, with_fp: bool = False) -> Carrier:
    """
    Create a minimal Carrier Python object directly (not via protobuf parsing).

    Used in tests that do not exercise protobuf deserialization but need
    a Carrier instance with or without a FrontPlane.

    Args:
        mac: MAC address for the carrier path.
        with_fp: If True, attach a FrontPlane to the carrier.

    Returns:
        A Carrier dataclass instance.
    """
    carrier_path = Path.parse(mac)
    cluster_path = carrier_path / "0"
    cluster = Cluster(
        path=cluster_path,
        m0block=MIntBlock(path=cluster_path / "M0"),
        ublock=UBlock(path=cluster_path / "U"),
        cblock=CBlock(path=cluster_path / "C"),
        iblock=IBlock(path=cluster_path / "I"),
        shblock=None,
    )

    fp = None
    if with_fp:
        fp = FrontPlane(carrier_path / "FP")

    # Try new keyword first, fall back to old keyword
    try:
        return Carrier(
            path=carrier_path,
            clusters=[cluster],
            tblock=None,
            front_plane=fp,
        )
    except TypeError:
        return Carrier(
            path=carrier_path,
            clusters=[cluster],
            tblock=None,
            front_panel=fp,
        )


class TestCarrierParseFrontPlane:

    def test_carrier_parses_fp_from_entity_tree(self):
        mac = AddressingMap.map_redac(0)
        carrier_pb = _make_carrier_entity(mac, include_fp=True)
        carrier_path = Path.parse(mac)

        from pybrid.lucidac.protocol.serializer import LUCIDACDeserializer
        carrier = LUCIDACDeserializer().deserialize_specification(carrier_pb, carrier_path)

        fp = getattr(carrier, "front_plane", None)
        assert fp is not None, (
            "Carrier parsed from entity tree with /FP child must have front_plane set"
        )
        assert fp.path.id_ == "FP", (
            f"FrontPlane path should end with 'FP', got '{fp.path.id_}'"
        )
        assert isinstance(fp, FrontPlane), (
            "front_plane must be a FrontPlane instance"
        )

    def test_carrier_without_fp(self):
        mac = AddressingMap.map_redac(0)
        carrier_pb = _make_carrier_entity(mac, include_fp=False)
        carrier_path = Path.parse(mac)

        carrier = REDACDeserializer().deserialize_specification(carrier_pb, carrier_path)

        fp = getattr(carrier, "front_plane", None)
        assert fp is None, (
            "Carrier parsed from entity tree without /FP child must have front_plane=None"
        )


class TestCarrierChildren:

    def test_carrier_children_includes_fp(self):
        mac = AddressingMap.map_redac(0)
        carrier = _make_minimal_carrier(mac, with_fp=True)

        children = list(carrier.children)
        fp_children = [c for c in children if isinstance(c, FrontPlane)]

        assert len(fp_children) == 1, (
            f"Expected exactly 1 FrontPlane in children, found {len(fp_children)}"
        )

        carrier_fp = getattr(carrier, "front_plane", None)
        assert carrier_fp is not None, (
            "carrier.front_plane must not be None when with_fp=True"
        )
        assert fp_children[0] is carrier_fp, (
            "The FrontPlane in children must be the same instance as carrier.front_plane"
        )

    def test_carrier_children_without_fp(self):
        mac = AddressingMap.map_redac(0)
        carrier = _make_minimal_carrier(mac, with_fp=False)

        children = list(carrier.children)
        fp_children = [c for c in children if isinstance(c, FrontPlane)]

        assert len(fp_children) == 0, (
            "Carrier without front_plane should not yield any FrontPlane in children"
        )


class TestLUCIStackFrontPlaneAccess:
    """FrontPlane is accessed via lucistack.entities[0].front_plane; no top-level convenience property exists on LUCIStack."""

    def test_lucistack_carrier_front_plane(self):
        mac = AddressingMap.map_redac(0)

        # Case 1: Carrier with FrontPlane
        carrier_with_fp = _make_minimal_carrier(mac, with_fp=True)
        lucistack_with_fp = LUCIStack(entities=[carrier_with_fp])

        carrier_fp = getattr(lucistack_with_fp.entities[0], "front_plane", None)
        assert carrier_fp is not None, (
            "LUCIStack carrier with FP must expose it via entities[0].front_plane"
        )
        assert isinstance(carrier_fp, FrontPlane), (
            "entities[0].front_plane must be a FrontPlane instance"
        )

        # Case 2: Carrier without FrontPlane
        carrier_without_fp = _make_minimal_carrier(mac, with_fp=False)
        lucistack_without_fp = LUCIStack(entities=[carrier_without_fp])

        carrier_no_fp = getattr(lucistack_without_fp.entities[0], "front_plane", None)
        assert carrier_no_fp is None, (
            "LUCIStack carrier without FP must have front_plane=None"
        )


class TestLUCIStackSerializationWithFP:

    def test_lucistack_serializer_fp_via_carrier_bfs(self):
        """Serializing a LUCIStack with a configured FrontPlane produces config entries at the FP entity path."""
        mac = AddressingMap.map_redac(0)
        carrier = _make_minimal_carrier(mac, with_fp=True)
        lucistack = LUCIStack(entities=[carrier])

        # Get the front plane via carrier (new access pattern)
        fp = getattr(carrier, "front_plane", None)
        if fp is None:
            # Fall back to old attribute for the purpose of configuring
            fp = getattr(carrier, "front_panel", None)

        assert fp is not None, (
            "Test setup: carrier must have a FrontPlane for serialization test"
        )

        # Configure the signal generator so serialization produces non-empty output
        fp.signal_generator.frequency = 1000.0
        fp.signal_generator.amplitude = 0.5
        fp.leds = 0xFF

        # Serialize via the LUCIStack serializer
        serializer_cls = lucistack.get_serializer()
        serializer = serializer_cls()
        module = serializer.serialize(lucistack)

        # Expected FP entity path: "<mac>/FP"
        expected_fp_path = str(Path.parse(mac) / "FP")

        # Find configs that reference the FrontPlane entity path
        fp_configs = [
            c for c in module.items
            if c.entity.path == expected_fp_path
        ]

        assert len(fp_configs) > 0, (
            f"Expected at least one config entry for entity path '{expected_fp_path}', "
            f"but found none. Config paths: {[c.entity.path for c in module.items]}"
        )

        # Verify that at least one config contains front_panel_config or
        # signal_generator_config (the two config types produced for FrontPlane)
        config_kinds = [c.WhichOneof('kind') for c in fp_configs]
        assert "front_panel_config" in config_kinds or "signal_generator_config" in config_kinds, (
            f"Expected front_panel_config or signal_generator_config in FP configs, "
            f"got kinds: {config_kinds}"
        )

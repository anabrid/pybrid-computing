# Copyright (c) 2022-2025 anabrid GmbH
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""Tests for the DummyDAC basic command handlers.

Uses the native C++ ControlChannel (via AsyncControlChannel) to exercise
DummyDAC over a real TCP connection — no internal Python Protocol mocking.
"""

import asyncio

import pytest

import pybrid.base.proto.main_pb2 as pb
from pybrid.mock import DummyDAC, DummyDACConfig, DummyDACErrorStage

try:
    from pybrid.native._impl import ControlChannel as NativeControlChannel
    from pybrid.redac.control import AsyncControlChannel

    _NATIVE_AVAILABLE = True
except ImportError:
    _NATIVE_AVAILABLE = False
    NativeControlChannel = None
    AsyncControlChannel = None

pytestmark = pytest.mark.skipif(
    not _NATIVE_AVAILABLE,
    reason="pybrid.native._impl.ControlChannel is not available (C++ bindings not built)",
)

LOCALHOST = "127.0.0.1"
OP_TIMEOUT = 5.0


async def _make_channel(port: int) -> "AsyncControlChannel":
    loop = asyncio.get_running_loop()
    native = await loop.run_in_executor(
        None,
        NativeControlChannel.create,
        LOCALHOST,
        port,
        OP_TIMEOUT,
    )
    channel = AsyncControlChannel(native)
    channel.start()
    return channel


# ---------------------------------------------------------------------------
# Extract: specification flag
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_specification_returns_entity_tree():
    """Extracting with specification=True returns EntitySpecification items
    representing the full hardware hierarchy, even when no config is stored."""
    config = DummyDACConfig()
    async with DummyDAC(LOCALHOST, 0, config) as server:
        port = server.port
        channel = await _make_channel(port)
        try:
            module = await asyncio.wait_for(
                channel.extract(specification=True, recursive=True),
                timeout=OP_TIMEOUT,
            )
            spec_items = [item for item in module.items if item.HasField("entity_specification")]
            assert len(spec_items) >= 1, f"Expected at least one EntitySpecification item, got {len(spec_items)}"
            # The root entity should contain carrier children.
            root_entity = spec_items[0].entity_specification.entity
            assert root_entity.class_ == pb.Entity.DEVICE
        finally:
            await channel.stop()


@pytest.mark.asyncio
async def test_extract_specification_redac_has_two_carriers():
    """In REDAC mode (default), the entity tree should contain 2 carriers
    without a FrontPanel entity."""
    config = DummyDACConfig()  # lucidac_mode=False => 2 carriers, no FP
    async with DummyDAC(LOCALHOST, 0, config) as server:
        port = server.port
        channel = await _make_channel(port)
        try:
            module = await asyncio.wait_for(
                channel.extract(specification=True, recursive=True),
                timeout=OP_TIMEOUT,
            )
            spec_items = [item for item in module.items if item.HasField("entity_specification")]
            root_entity = spec_items[0].entity_specification.entity
            assert len(root_entity.children) == 2, f"Expected 2 carriers in REDAC mode, got {len(root_entity.children)}"
            for carrier in root_entity.children:
                child_ids = [c.id for c in carrier.children]
                assert "/FP" not in child_ids, f"FP should not appear in REDAC carrier children, got: {child_ids}"
        finally:
            await channel.stop()


@pytest.mark.asyncio
async def test_extract_specification_lucidac_has_frontpanel():
    """In LUCIDAC mode, the entity tree should include a FrontPanel entity."""
    config = DummyDACConfig(lucidac_mode=True)
    async with DummyDAC(LOCALHOST, 0, config) as server:
        port = server.port
        channel = await _make_channel(port)
        try:
            module = await asyncio.wait_for(
                channel.extract(specification=True, recursive=True),
                timeout=OP_TIMEOUT,
            )
            spec_items = [item for item in module.items if item.HasField("entity_specification")]
            root_entity = spec_items[0].entity_specification.entity
            assert (
                len(root_entity.children) == 1
            ), f"Expected 1 carrier in LUCIDAC mode, got {len(root_entity.children)}"
            carrier = root_entity.children[0]
            child_ids = [c.id for c in carrier.children]
            assert "/FP" in child_ids, f"FP should appear in LUCIDAC carrier children, got: {child_ids}"
        finally:
            await channel.stop()


# ---------------------------------------------------------------------------
# Extract: configuration flag
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_configuration_returns_stored_items():
    """Extracting with configuration=True returns previously stored config items."""
    config = DummyDACConfig()
    async with DummyDAC(LOCALHOST, 0, config) as server:
        port = server.port
        channel = await _make_channel(port)
        try:
            test_item = pb.Item(entity=pb.EntityId(path="/00-00-00-00-00-00/0/M0"))
            module = pb.Module(items=[test_item])
            await asyncio.wait_for(channel.set_module(module), timeout=OP_TIMEOUT)

            module = await asyncio.wait_for(
                channel.extract(
                    "/00-00-00-00-00-00",
                    configuration=True,
                    recursive=True,
                ),
                timeout=OP_TIMEOUT,
            )
            # Should contain the stored config item (non-spec items).
            non_spec = [item for item in module.items if not item.HasField("entity_specification")]
            assert len(non_spec) == 1, f"Expected 1 config item, got {len(non_spec)}"
        finally:
            await channel.stop()


@pytest.mark.asyncio
async def test_extract_configuration_filtered_by_path():
    """Extracting configuration with a path prefix returns only matching items."""
    config = DummyDACConfig()
    async with DummyDAC(LOCALHOST, 0, config) as server:
        port = server.port
        channel = await _make_channel(port)
        try:
            items = [
                pb.Item(entity=pb.EntityId(path="/00-00-00-00-00-00/0/M0")),
                pb.Item(entity=pb.EntityId(path="/00-00-00-00-00-00/0/M1")),
                pb.Item(entity=pb.EntityId(path="/00-00-00-00-00-01/0/M0")),
            ]
            module = pb.Module(items=items)
            await asyncio.wait_for(channel.set_module(module), timeout=OP_TIMEOUT)

            module = await asyncio.wait_for(
                channel.extract(
                    "/00-00-00-00-00-00",
                    configuration=True,
                    recursive=True,
                ),
                timeout=OP_TIMEOUT,
            )
            non_spec = [item for item in module.items if not item.HasField("entity_specification")]
            assert len(non_spec) == 2, f"Expected 2 config items for /00-00-00-00-00-00, got {len(non_spec)}"
        finally:
            await channel.stop()


# ---------------------------------------------------------------------------
# Extract: combined flags and edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_both_spec_and_config():
    """When both specification and configuration are True, the response contains both
    EntitySpecification items and operational config items."""
    config = DummyDACConfig()
    async with DummyDAC(LOCALHOST, 0, config) as server:
        port = server.port
        channel = await _make_channel(port)
        try:
            test_item = pb.Item(entity=pb.EntityId(path="/00-00-00-00-00-00/0/M0"))
            module = pb.Module(items=[test_item])
            await asyncio.wait_for(channel.set_module(module), timeout=OP_TIMEOUT)

            module = await asyncio.wait_for(
                channel.extract(
                    specification=True,
                    configuration=True,
                    recursive=True,
                ),
                timeout=OP_TIMEOUT,
            )
            spec_items = [item for item in module.items if item.HasField("entity_specification")]
            config_items = [item for item in module.items if not item.HasField("entity_specification")]
            assert len(spec_items) >= 1, "Should include entity specification items"
            assert len(config_items) >= 1, "Should include config items"
        finally:
            await channel.stop()


@pytest.mark.asyncio
async def test_extract_neither_flag_returns_empty():
    """When neither specification nor configuration is requested, extract returns
    an empty module."""
    config = DummyDACConfig()
    async with DummyDAC(LOCALHOST, 0, config) as server:
        port = server.port
        channel = await _make_channel(port)
        try:
            # Store some config so there's data available.
            test_item = pb.Item(entity=pb.EntityId(path="/00-00-00-00-00-00/0/M0"))
            module = pb.Module(items=[test_item])
            await asyncio.wait_for(channel.set_module(module), timeout=OP_TIMEOUT)

            module = await asyncio.wait_for(
                channel.extract(
                    specification=False,
                    configuration=False,
                    recursive=True,
                ),
                timeout=OP_TIMEOUT,
            )
            assert len(module.items) == 0, f"Expected empty module when no flags are set, got {len(module.items)} items"
        finally:
            await channel.stop()


# ---------------------------------------------------------------------------
# Config and Reset handlers (proto type fixes)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_config_stores_module():
    """Storing a config via set_module persists the items on the server."""
    config = DummyDACConfig()
    async with DummyDAC(LOCALHOST, 0, config) as server:
        port = server.port
        channel = await _make_channel(port)
        try:
            test_item = pb.Item(entity=pb.EntityId(path="/00-00-00-00-00-00/0/M0"))
            module = pb.Module(items=[test_item])
            result = await asyncio.wait_for(channel.set_module(module), timeout=OP_TIMEOUT)
            assert result.ok, "set_module() should return a successful Result"
            assert server._stored_config is not None, "Server should have stored the config"
            assert (
                len(server._stored_config.items) == 1
            ), f"Expected 1 item stored, got {len(server._stored_config.items)}"
        finally:
            await channel.stop()


@pytest.mark.asyncio
async def test_reset_clears_config():
    """Reset should clear any stored configuration."""
    config = DummyDACConfig()
    async with DummyDAC(LOCALHOST, 0, config) as server:
        port = server.port
        channel = await _make_channel(port)
        try:
            test_item = pb.Item(entity=pb.EntityId(path="/00-00-00-00-00-00/0/M0"))
            module = pb.Module(items=[test_item])
            await asyncio.wait_for(channel.set_module(module), timeout=OP_TIMEOUT)
            assert server._stored_config is not None

            await asyncio.wait_for(channel.reset(), timeout=OP_TIMEOUT)
            assert server._stored_config is None, "Reset should clear stored config"
        finally:
            await channel.stop()


@pytest.mark.asyncio
async def test_config_error_injection():
    """AT_CONFIGURE error injection surfaces as a failure Result."""
    config = DummyDACConfig(
        error_stage=DummyDACErrorStage.AT_CONFIGURE,
        error_message="Simulated config error",
    )
    async with DummyDAC(LOCALHOST, 0, config) as server:
        port = server.port
        channel = await _make_channel(port)
        try:
            test_item = pb.Item(entity=pb.EntityId(path="/test"))
            module = pb.Module(items=[test_item])
            result = await asyncio.wait_for(channel.set_module(module), timeout=OP_TIMEOUT)
            assert result.ok is False
            assert "Simulated config error" in result.error
        finally:
            await channel.stop()

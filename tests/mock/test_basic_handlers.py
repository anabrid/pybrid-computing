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
from pybrid.redac.control import AsyncControlChannel

try:
    from pybrid.native._impl import ControlChannel as NativeControlChannel
    _NATIVE_AVAILABLE = True
except ImportError:
    _NATIVE_AVAILABLE = False
    NativeControlChannel = None

pytestmark = pytest.mark.skipif(
    not _NATIVE_AVAILABLE,
    reason="pybrid.native._impl.ControlChannel is not available (C++ bindings not built)",
)

LOCALHOST = "127.0.0.1"
OP_TIMEOUT = 5.0


async def _make_channel(port: int) -> AsyncControlChannel:
    """
    Create and start an AsyncControlChannel connected to *port* on localhost.

    Wraps the native ControlChannel creation in an executor so the asyncio
    event loop is not blocked during TCP connect.

    Args:
        port: TCP port of the target DummyDAC server.

    Returns:
        A started :class:`AsyncControlChannel`.
    """
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


@pytest.mark.asyncio
async def test_describe_returns_entity_tree():
    config = DummyDACConfig()  # lucidac_mode=False => 2 carriers, no FrontPanel
    async with DummyDAC(LOCALHOST, 0, config) as server:
        port = server.port
        channel = await _make_channel(port)
        try:
            entity = await asyncio.wait_for(channel.describe(), timeout=OP_TIMEOUT)
            assert len(entity.children) == 2, (
                f"Expected exactly 2 carriers in REDAC mode, got {len(entity.children)}"
            )
            for carrier in entity.children:
                child_ids = [c.id for c in carrier.children]
                assert "FP" not in child_ids, (
                    f"FP should not appear in REDAC carrier children, got: {child_ids}"
                )
        finally:
            await channel.stop()


@pytest.mark.asyncio
async def test_config_stores_bundle():
    config = DummyDACConfig()
    async with DummyDAC(LOCALHOST, 0, config) as server:
        port = server.port
        channel = await _make_channel(port)
        try:
            test_config = pb.Config(entity=pb.EntityId(path="/00-00-00-00-00-00/0/M0"))
            bundle = pb.ConfigBundle(configs=[test_config])
            result = await asyncio.wait_for(
                channel.set_config_bundle(bundle), timeout=OP_TIMEOUT
            )
            assert result.ok, "set_config_bundle() should return a successful Result"
            assert server._stored_config is not None, "Server should have stored the config"
            assert len(server._stored_config.configs) == 1, (
                f"Expected 1 config entry stored, got {len(server._stored_config.configs)}"
            )
        finally:
            await channel.stop()


@pytest.mark.asyncio
async def test_reset_clears_config():
    config = DummyDACConfig()
    async with DummyDAC(LOCALHOST, 0, config) as server:
        port = server.port
        channel = await _make_channel(port)
        try:
            # First store a config.
            test_config = pb.Config(entity=pb.EntityId(path="/00-00-00-00-00-00/0/M0"))
            bundle = pb.ConfigBundle(configs=[test_config])
            await asyncio.wait_for(channel.set_config_bundle(bundle), timeout=OP_TIMEOUT)
            assert server._stored_config is not None, "Config should be stored before reset"

            # Now reset — should clear the stored config.
            await asyncio.wait_for(channel.reset(), timeout=OP_TIMEOUT)
            assert server._stored_config is None, "Reset should clear stored config"
        finally:
            await channel.stop()


@pytest.mark.asyncio
async def test_config_error_injection():
    """AT_CONFIGURE error injection surfaces as a failure Result from set_config_bundle."""
    config = DummyDACConfig(
        error_stage=DummyDACErrorStage.AT_CONFIGURE,
        error_message="Simulated config error",
    )
    async with DummyDAC(LOCALHOST, 0, config) as server:
        port = server.port
        channel = await _make_channel(port)
        try:
            test_config = pb.Config(entity=pb.EntityId(path="/test"))
            bundle = pb.ConfigBundle(configs=[test_config])
            result = await asyncio.wait_for(
                channel.set_config_bundle(bundle), timeout=OP_TIMEOUT
            )
            assert result.ok is False, (
                "set_config_bundle() must return a failure Result for AT_CONFIGURE error injection"
            )
            assert "Simulated config error" in result.error, (
                f"Result.error must contain the device error description, got: {result.error!r}"
            )
        finally:
            await channel.stop()


@pytest.mark.asyncio
async def test_extract_returns_filtered_configs():
    config = DummyDACConfig()
    async with DummyDAC(LOCALHOST, 0, config) as server:
        port = server.port
        channel = await _make_channel(port)
        try:
            configs = [
                pb.Config(entity=pb.EntityId(path="/00-00-00-00-00-00/0/M0")),
                pb.Config(entity=pb.EntityId(path="/00-00-00-00-00-00/0/M1")),
                pb.Config(entity=pb.EntityId(path="/00-00-00-00-00-01/0/M0")),
            ]
            bundle = pb.ConfigBundle(configs=configs)
            await asyncio.wait_for(channel.set_config_bundle(bundle), timeout=OP_TIMEOUT)

            # Extract only the first carrier's configs.
            result = await asyncio.wait_for(
                channel.get_config("/00-00-00-00-00-00", recursive=True),
                timeout=OP_TIMEOUT,
            )
            assert len(result.configs) == 2, (
                f"Expected 2 configs for /00-00-00-00-00-00, got {len(result.configs)}"
            )
        finally:
            await channel.stop()

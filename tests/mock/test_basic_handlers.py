# Copyright (c) 2022-2025 anabrid GmbH
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""Tests for the DummyDAC basic command handlers."""

from ipaddress import IPv4Address

import pytest

import pybrid.base.proto.main_pb2 as pb
from pybrid.base.transport.tcp import TCPTransport
from pybrid.mock import DummyDAC, DummyDACConfig, DummyDACErrorStage
from pybrid.redac.entities import Path
from pybrid.redac.protocol.protocol import Protocol


@pytest.mark.asyncio
async def test_describe_returns_entity_tree():
    """Verify describe command returns entity tree."""
    config = DummyDACConfig()
    async with DummyDAC("127.0.0.1", 15800, config):
        transport = await TCPTransport.create("127.0.0.1", 15800)
        protocol = Protocol(IPv4Address("127.0.0.1"), transport)
        async with protocol:
            entity = await protocol.get_entity()
            assert len(entity.children) == 2


@pytest.mark.asyncio
async def test_entity_tree_has_no_fp():
    """Verify entity tree excludes /FP block."""
    config = DummyDACConfig()
    async with DummyDAC("127.0.0.1", 15801, config):
        transport = await TCPTransport.create("127.0.0.1", 15801)
        protocol = Protocol(IPv4Address("127.0.0.1"), transport)
        async with protocol:
            entity = await protocol.get_entity()
            for carrier in entity.children:
                child_ids = [c.id for c in carrier.children]
                assert "FP" not in child_ids


@pytest.mark.asyncio
async def test_config_stores_bundle():
    """Verify config command stores the bundle."""
    config = DummyDACConfig()
    async with DummyDAC("127.0.0.1", 15802, config) as server:
        transport = await TCPTransport.create("127.0.0.1", 15802)
        protocol = Protocol(IPv4Address("127.0.0.1"), transport)
        async with protocol:
            test_config = pb.Config(entity=pb.EntityId(path="/00-00-00-00-00-00/0/M0"))
            bundle = pb.ConfigBundle(configs=[test_config])
            await protocol.set_config_bundle(bundle)
            assert server._stored_config is not None
            assert len(server._stored_config.configs) == 1


@pytest.mark.asyncio
async def test_reset_clears_config():
    """Verify reset command clears stored config."""
    config = DummyDACConfig()
    async with DummyDAC("127.0.0.1", 15803, config) as server:
        transport = await TCPTransport.create("127.0.0.1", 15803)
        protocol = Protocol(IPv4Address("127.0.0.1"), transport)
        async with protocol:
            test_config = pb.Config(entity=pb.EntityId(path="/00-00-00-00-00-00/0/M0"))
            bundle = pb.ConfigBundle(configs=[test_config])
            await protocol.set_config_bundle(bundle)
            assert server._stored_config is not None
            await protocol.reset()
            assert server._stored_config is None


@pytest.mark.asyncio
async def test_config_error_injection():
    """Verify AT_CONFIGURE error injection works."""
    config = DummyDACConfig(
        error_stage=DummyDACErrorStage.AT_CONFIGURE,
        error_message="Simulated config error"
    )
    async with DummyDAC("127.0.0.1", 15804, config):
        transport = await TCPTransport.create("127.0.0.1", 15804)
        protocol = Protocol(IPv4Address("127.0.0.1"), transport)
        async with protocol:
            test_config = pb.Config(entity=pb.EntityId(path="/test"))
            bundle = pb.ConfigBundle(configs=[test_config])
            response = await protocol.set_config_bundle(bundle)
            assert response.WhichOneof("kind") == "error_message"
            assert "Simulated config error" in response.error_message.description


@pytest.mark.asyncio
async def test_extract_returns_filtered_configs():
    """Verify extract returns configs matching path."""
    config = DummyDACConfig()
    async with DummyDAC("127.0.0.1", 15805, config):
        transport = await TCPTransport.create("127.0.0.1", 15805)
        protocol = Protocol(IPv4Address("127.0.0.1"), transport)
        async with protocol:
            configs = [
                pb.Config(entity=pb.EntityId(path="/00-00-00-00-00-00/0/M0")),
                pb.Config(entity=pb.EntityId(path="/00-00-00-00-00-00/0/M1")),
                pb.Config(entity=pb.EntityId(path="/00-00-00-00-00-01/0/M0")),
            ]
            bundle = pb.ConfigBundle(configs=configs)
            await protocol.set_config_bundle(bundle)
            result = await protocol.get_config(Path.parse("/00-00-00-00-00-00"))
            assert len(result.configs) == 2

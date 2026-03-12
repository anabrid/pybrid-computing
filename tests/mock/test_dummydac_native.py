# Copyright (c) 2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
Integration tests: DummyDAC Python server <-> native C++ ControlChannel client.

These tests verify cross-language interoperability: the Python DummyDAC TCP
server correctly handles the varint-framed protobuf wire format used by the
native C++ ControlChannel (AsyncControlChannel wrapper).

Each test creates a DummyDAC on an ephemeral port (port=0), then connects one
or more AsyncControlChannel clients to exercise real TCP flows — no internal
mocking.

Run with:
    uv run pytest tests/mock/test_dummydac_native.py -v
"""

import asyncio
from uuid import uuid4

import pytest

import pybrid.base.proto.main_pb2 as pb
from pybrid.mock import DummyDAC, DummyDACConfig
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
# Timeout for individual roundtrip operations.
OP_TIMEOUT = 5.0
# Short run op-time (50 ms) — keeps run lifecycle tests fast.
RUN_OP_TIME_NS = 50_000_000  # 50 ms
# Budget for the entire run including state callbacks (op-time + 2 s headroom).
RUN_TIMEOUT = RUN_OP_TIME_NS / 1e9 + 2.0


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
async def test_describe_via_native_channel():
    """Describe returns the correct LUCIDAC entity tree with one carrier and FP in LUCIDAC mode."""
    config = DummyDACConfig(lucidac_mode=True)
    async with DummyDAC(LOCALHOST, 0, config) as server:
        port = server.port
        channel = await _make_channel(port)
        try:
            module = await asyncio.wait_for(
                channel.extract(specification=True, recursive=True), timeout=OP_TIMEOUT
            )
            entity = module.items[0].entity_specification.entity

            # Root entity must have exactly one carrier in LUCIDAC mode.
            assert len(entity.children) == 1, (
                f"Expected exactly 1 carrier in LUCIDAC mode, got {len(entity.children)}"
            )

            carrier = entity.children[0]

            # Carrier must include a cluster with id "/0" (firmware wire format uses '/' prefix).
            cluster_ids = {c.id for c in carrier.children}
            assert "/0" in cluster_ids, (
                f"Expected cluster with id '/0' under carrier, got: {cluster_ids}"
            )

            # Locate the cluster child.
            cluster = next(c for c in carrier.children if c.id == "/0")

            # Cluster must contain all expected analog blocks.
            block_ids = {c.id for c in cluster.children}
            expected_blocks = {"/M0", "/M1", "/U", "/C", "/I", "/SH"}
            assert expected_blocks.issubset(block_ids), (
                f"Cluster is missing blocks. Expected {expected_blocks}, found {block_ids}"
            )

            # LUCIDAC mode must include FrontPanel entity (id "/FP") on the carrier.
            assert "/FP" in cluster_ids, (
                f"Expected FrontPanel '/FP' as carrier child in LUCIDAC mode, got: {cluster_ids}"
            )
        finally:
            await channel.stop()


@pytest.mark.asyncio
async def test_reset_via_native_channel():
    """reset() completes without error; an exception would indicate a failure response."""
    config = DummyDACConfig(lucidac_mode=True)
    async with DummyDAC(LOCALHOST, 0, config) as server:
        port = server.port
        channel = await _make_channel(port)
        try:
            # reset() raises RuntimeError if the device responds with an error.
            await asyncio.wait_for(channel.reset(), timeout=OP_TIMEOUT)
        finally:
            await channel.stop()


@pytest.mark.asyncio
async def test_config_set_and_extract_via_native_channel():
    """Config stored via set_module() is retrievable via extract(configuration=True)."""
    config = DummyDACConfig(lucidac_mode=True)
    async with DummyDAC(LOCALHOST, 0, config) as server:
        port = server.port
        channel = await _make_channel(port)
        try:
            # Step 1: discover carrier path.
            module = await asyncio.wait_for(
                channel.extract(specification=True, recursive=True), timeout=OP_TIMEOUT
            )
            entity = module.items[0].entity_specification.entity
            assert len(entity.children) >= 1, "Expected at least one carrier"
            # Entity ids use the firmware wire format with a leading '/'.
            carrier_path = entity.children[0].id

            # Step 2: build a non-trivial config module.
            module = pb.Module()
            cfg = module.items.add()
            cfg.entity.path = carrier_path
            adc_ch = cfg.adc_config.channels.add()
            adc_ch.idx = 0
            adc_ch.gain = 2.0
            adc_ch.offset = 0.5

            # Step 3: push config to DummyDAC.
            result = await asyncio.wait_for(
                channel.set_module(module), timeout=OP_TIMEOUT
            )
            assert result.ok, "set_module() should return a successful Result"

            # Step 4: retrieve config back.
            retrieved = await asyncio.wait_for(
                channel.extract(carrier_path, configuration=True, recursive=False), timeout=OP_TIMEOUT
            )

            # Step 5: verify the retrieved module is non-empty and path matches.
            assert len(retrieved.items) >= 1, (
                "Expected at least one config entry after set+extract roundtrip"
            )
            paths = {c.entity.path for c in retrieved.items}
            assert carrier_path in paths, (
                f"Carrier path '{carrier_path}' not found in extracted config paths: {paths}"
            )
        finally:
            await channel.stop()


@pytest.mark.asyncio
async def test_run_lifecycle_via_native_channel():
    """Full run lifecycle produces the expected state sequence: TAKE_OFF -> IC -> OP -> OP_END -> DONE."""
    config = DummyDACConfig(lucidac_mode=True)
    async with DummyDAC(LOCALHOST, 0, config) as server:
        port = server.port
        channel = await _make_channel(port)
        loop = asyncio.get_running_loop()

        states_received: list[int] = []
        done_event = asyncio.Event()

        def on_state_change(msg: pb.MessageV1) -> None:
            new_state = msg.run_state_change_message.new_
            states_received.append(new_state)
            if new_state == pb.RunState.DONE:
                loop.call_soon_threadsafe(done_event.set)

        channel.register_callback(
            pb.MessageV1.RUN_STATE_CHANGE_MESSAGE_FIELD_NUMBER,
            on_state_change,
        )

        try:
            cmd = pb.StartRunCommand(
                run=pb.Run(id=str(uuid4()), chunk=0),
                run_config=pb.RunConfig(
                    ic_time=pb.Time(value=1000, prefix=pb.Prefix.NANO),
                    op_time=pb.Time(value=RUN_OP_TIME_NS, prefix=pb.Prefix.NANO),
                    halt_on_overload=False,
                ),
                daq_config=pb.DaqConfig(
                    num_channels=2,
                    sample_rate=100_000,
                    sample_op=True,
                    sample_op_end=True,
                ),
                sync_config=pb.SyncConfig(enabled=False),
            )

            # Start the run — waits for acceptance acknowledgement only.
            await asyncio.wait_for(channel.start_run_request(cmd), timeout=OP_TIMEOUT)

            # Wait for the run to reach DONE state.
            await asyncio.wait_for(done_event.wait(), timeout=RUN_TIMEOUT)

            # Verify the expected state machine progression.
            assert pb.RunState.TAKE_OFF in states_received, (
                f"TAKE_OFF missing from states: {states_received}"
            )
            assert pb.RunState.IC in states_received, (
                f"IC missing from states: {states_received}"
            )
            assert pb.RunState.OP in states_received, (
                f"OP missing from states: {states_received}"
            )
            assert pb.RunState.OP_END in states_received, (
                f"OP_END missing from states: {states_received}"
            )
            assert pb.RunState.DONE in states_received, (
                f"DONE missing from states: {states_received}"
            )
        finally:
            await channel.stop()


@pytest.mark.asyncio
async def test_sequential_clients():
    """Two sequential clients each receive the same entity tree from the same DummyDAC instance."""
    config = DummyDACConfig(lucidac_mode=True)
    async with DummyDAC(LOCALHOST, 0, config) as server:
        port = server.port

        # --- First client ---
        channel1 = await _make_channel(port)
        try:
            module1 = await asyncio.wait_for(
                channel1.extract(specification=True, recursive=True), timeout=OP_TIMEOUT
            )
            entity1 = module1.items[0].entity_specification.entity
            assert len(entity1.children) == 1, (
                f"Client 1: expected 1 carrier, got {len(entity1.children)}"
            )
            carrier_id_1 = entity1.children[0].id
        finally:
            await channel1.stop()

        # Give DummyDAC a moment to fully close the first connection.
        await asyncio.sleep(0.1)

        # --- Second client ---
        channel2 = await _make_channel(port)
        try:
            module2 = await asyncio.wait_for(
                channel2.extract(specification=True, recursive=True), timeout=OP_TIMEOUT
            )
            entity2 = module2.items[0].entity_specification.entity
            assert len(entity2.children) == 1, (
                f"Client 2: expected 1 carrier, got {len(entity2.children)}"
            )
            carrier_id_2 = entity2.children[0].id
        finally:
            await channel2.stop()

        # Both clients must see the same carrier (same DummyDAC instance).
        assert carrier_id_1 == carrier_id_2, (
            f"Both clients should see the same carrier MAC. "
            f"Client 1: {carrier_id_1}, Client 2: {carrier_id_2}"
        )

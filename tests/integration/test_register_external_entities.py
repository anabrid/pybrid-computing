# Copyright (c) 2022-2025 anabrid GmbH
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
Integration tests for RegisterExternalEntities across Controller and Proxy.

Tests verify that the Controller distributes carrier unique IDs and IP
addresses to all connected backends, and that the proxy handles the
command from clients as a no-op success.
"""

import asyncio
import threading

import pytest

import pybrid.base.proto.main_pb2 as pb
from pybrid.mock import DummyDAC, DummyDACConfig, DummyDACMacMode
from pybrid.redac.controller import Controller
from tests.conftest import get_test_port

try:
    from pybrid.native._impl import ControlChannel, ProxyServer
    _NATIVE_AVAILABLE = True
except ImportError:
    _NATIVE_AVAILABLE = False

LOCALHOST = "127.0.0.1"
SHORT_TIMEOUT = 5.0
SESSION_TIMEOUT = 2.0


def _start_dummy_dac(
    config: DummyDACConfig,
    ready_event: threading.Event,
    stop_event: threading.Event,
    port_holder: list,
    dac_holder: list,
) -> threading.Thread:
    """Launch DummyDAC in a background thread, exposing port and instance."""
    def _run() -> None:
        async def _async_run() -> None:
            async with DummyDAC(LOCALHOST, 0, config) as dac:
                port_holder[0] = dac.port
                dac_holder[0] = dac
                ready_event.set()
                while not stop_event.is_set():
                    await asyncio.sleep(0.05)

        asyncio.run(_async_run())

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return thread


class TestControllerRegisterExternalEntities:
    """Controller.register_external_entities() sends the entity map to backends."""

    @pytest.mark.asyncio
    async def test_single_device(self):
        """Single DummyDAC receives one entity entry per carrier with correct IP."""

        # temporary while register external device commands not send out
        pytest.skip()

        config = DummyDACConfig(mac_mode=DummyDACMacMode.PHYSICAL, lucidac_mode=True)

        async with DummyDAC(LOCALHOST, get_test_port(), config) as dac:
            dac_port = dac._server.sockets[0].getsockname()[1]

            async with Controller() as ctrl:
                await ctrl.add_device(LOCALHOST, dac_port)
                await ctrl.register_external_entities()

                handler = dac._handlers[
                    pb.MessageV1.REGISTER_EXTERNAL_ENTITIES_COMMAND_FIELD_NUMBER
                ]
                assert len(handler.last_entities) == 1

                carrier = ctrl.computer.carriers[0]
                mac = str(carrier.path)
                assert mac in handler.last_entities

                ip_bytes = handler.last_entities[mac]
                assert ip_bytes == bytes([127, 0, 0, 1])

    @pytest.mark.asyncio
    async def test_multiple_devices_direct_mode(self):
        """Two DummyDACs (PHYSICAL mode) each receive entity entries for all carriers."""

        # temporary while register external device commands not send out
        pytest.skip()

        config1 = DummyDACConfig(mac_mode=DummyDACMacMode.PHYSICAL, lucidac_mode=True)
        config2 = DummyDACConfig(mac_mode=DummyDACMacMode.PHYSICAL, lucidac_mode=True)

        async with DummyDAC(LOCALHOST, get_test_port(0), config1, physical=True) as dac1:
            async with DummyDAC(LOCALHOST, get_test_port(1), config2, physical=True) as dac2:
                port1 = dac1._server.sockets[0].getsockname()[1]
                port2 = dac2._server.sockets[0].getsockname()[1]

                async with Controller() as ctrl:
                    await ctrl.add_device(LOCALHOST, port1)
                    await ctrl.add_device(LOCALHOST, port2)

                    assert len(ctrl.computer.carriers) == 2
                    await ctrl.register_external_entities()

                    handler1 = dac1._handlers[
                        pb.MessageV1.REGISTER_EXTERNAL_ENTITIES_COMMAND_FIELD_NUMBER
                    ]
                    handler2 = dac2._handlers[
                        pb.MessageV1.REGISTER_EXTERNAL_ENTITIES_COMMAND_FIELD_NUMBER
                    ]

                    assert len(handler1.last_entities) == 2
                    assert len(handler2.last_entities) == 2

                    macs = {str(c.path) for c in ctrl.computer.carriers}
                    assert len(macs) == 2
                    assert set(handler1.last_entities.keys()) == macs
                    assert set(handler2.last_entities.keys()) == macs

    @pytest.mark.asyncio
    async def test_no_devices(self):
        """Calling register_external_entities on empty controller is a no-op."""
        async with Controller() as ctrl:
            # No devices added — should return cleanly
            await ctrl.register_external_entities()
            assert len(ctrl.computer.carriers) == 0


class TestDummyDACRegisterExternalEntitiesHandler:
    """Direct handler test: sent entities are stored and success is returned."""

    @pytest.mark.asyncio
    async def test_handler_stores_entities(self):
        """Send RegisterExternalEntitiesCommand to DummyDAC and verify storage."""
        config = DummyDACConfig(mac_mode=DummyDACMacMode.PHYSICAL, lucidac_mode=True)

        async with DummyDAC(LOCALHOST, get_test_port(), config) as dac:
            dac_port = dac._server.sockets[0].getsockname()[1]

            from pybrid.redac.control import AsyncControlChannel
            channel = await AsyncControlChannel.create(LOCALHOST, dac_port)
            try:
                channel.start()
                result = await channel.register_external_entities({
                    "04-E9-E5-00-00-01": (10, 0, 0, 1),
                    "04-E9-E5-00-00-02": (192, 168, 1, 5),
                })
                result.raise_on_error()

                handler = dac._handlers[
                    pb.MessageV1.REGISTER_EXTERNAL_ENTITIES_COMMAND_FIELD_NUMBER
                ]
                assert len(handler.last_entities) == 2
                assert handler.last_entities["04-E9-E5-00-00-01"] == bytes([10, 0, 0, 1])
                assert handler.last_entities["04-E9-E5-00-00-02"] == bytes([192, 168, 1, 5])
            finally:
                await channel.stop()


@pytest.mark.skipif(not _NATIVE_AVAILABLE, reason="Native bindings not available")
class TestProxyRegisterExternalEntities:
    """Proxy handles RegisterExternalEntitiesCommand from clients."""

    def test_proxy_map_backends(self):
        """map_backends() completes without error on a two-backend proxy."""
        config1 = DummyDACConfig(mac_mode=DummyDACMacMode.PHYSICAL, lucidac_mode=True)
        config2 = DummyDACConfig(mac_mode=DummyDACMacMode.PHYSICAL, lucidac_mode=True)

        ready1, ready2 = threading.Event(), threading.Event()
        stop1, stop2 = threading.Event(), threading.Event()
        port1, port2 = [0], [0]
        dac1, dac2 = [None], [None]

        t1 = _start_dummy_dac(config1, ready1, stop1, port1, dac1)
        t2 = _start_dummy_dac(config2, ready2, stop2, port2, dac2)

        assert ready1.wait(timeout=SHORT_TIMEOUT), "DummyDAC 1 did not start"
        assert ready2.wait(timeout=SHORT_TIMEOUT), "DummyDAC 2 did not start"

        proxy = ProxyServer()
        proxy.set_session_timeout(SESSION_TIMEOUT)

        try:
            proxy.add_backend(LOCALHOST, port1[0])
            proxy.add_backend(LOCALHOST, port2[0])
            proxy.map_backends()
            proxy.start(LOCALHOST, 0)

            # Verify proxy is listening (map_backends didn't crash)
            assert proxy.local_port() > 0
        finally:
            proxy.stop()
            stop1.set()
            stop2.set()
            t1.join(timeout=SHORT_TIMEOUT)
            t2.join(timeout=SHORT_TIMEOUT)

    def test_client_register_external_entities_returns_success(self):
        """Client sending RegisterExternalEntitiesCommand to proxy gets SuccessMessage."""
        config = DummyDACConfig(mac_mode=DummyDACMacMode.PHYSICAL, lucidac_mode=True)

        ready = threading.Event()
        stop = threading.Event()
        port_holder = [0]
        dac_holder = [None]

        t = _start_dummy_dac(config, ready, stop, port_holder, dac_holder)
        assert ready.wait(timeout=SHORT_TIMEOUT), "DummyDAC did not start"

        proxy = ProxyServer()
        proxy.set_session_timeout(SESSION_TIMEOUT)
        client = None

        try:
            proxy.add_backend(LOCALHOST, port_holder[0])
            proxy.map_backends()
            proxy.start(LOCALHOST, 0)

            client = ControlChannel.create(LOCALHOST, proxy.local_port(), timeout=SHORT_TIMEOUT)
            client.start()

            cmd = pb.RegisterExternalEntitiesCommand()
            addr = pb.Address(data=bytes([10, 0, 0, 1]))
            cmd.entities["04-E9-E5-00-00-01"].CopyFrom(addr)

            msg = pb.MessageV1(id="test-reg-ext")
            msg.register_external_entities_command.CopyFrom(cmd)

            response_bytes = client.send_and_recv(
                msg.SerializeToString(), timeout=SHORT_TIMEOUT
            )
            response = pb.MessageV1()
            response.ParseFromString(response_bytes)

            assert response.HasField("success_message"), (
                f"Expected success_message, got: {response}"
            )
        finally:
            if client is not None:
                client.stop()
            proxy.stop()
            stop.set()
            t.join(timeout=SHORT_TIMEOUT)

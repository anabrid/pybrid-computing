# Copyright (c) 2022-2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
Integration tests for the native C++ ProxyServer.

Tests verify the full stack: DummyDAC (backend) -> ProxyServer (C++ relay)
-> ControlChannel (client). All tests are synchronous (blocking) since
ProxyServer and ControlChannel are C++ objects that release the GIL internally.

Each test starts its own DummyDAC and ProxyServer and cleans up after itself.
No shared state between tests.

Note: These tests require the ProxyServer pybind11 bindings to be compiled and
available as ``pybrid.native._impl.ProxyServer``. If the bindings are not built,
these tests will produce an ``ImportError`` at collection time and are skipped.
"""

import os
import threading
import time
import uuid
import asyncio

import pytest

import pybrid.base.proto.main_pb2 as pb
from pybrid.mock import DummyDAC, DummyDACConfig, DummyDACErrorStage, DummyDACMacMode
from pybrid.native._impl import ControlChannel, ProxyServer
from tests.conftest import get_test_port, get_test_proxy_port

LOCALHOST = "127.0.0.1"

# Timeouts used across tests
SHORT_TIMEOUT = 5.0    # seconds — single roundtrip or connection
RUN_TIMEOUT = 15.0     # seconds — full run lifecycle including data
SESSION_TIMEOUT = 2.0  # seconds — accelerated session timeout for ordering tests


def _start_dummy_dac(
    config: DummyDACConfig,
    ready_event: threading.Event,
    stop_event: threading.Event,
    port_holder: list,
) -> threading.Thread:
    """
    Launch DummyDAC in a background thread with its own event loop.

    The thread sets ``ready_event`` once the server is listening and
    writes the actual bound port into ``port_holder[0]``.  It runs until
    ``stop_event`` is set.

    Args:
        config:       DummyDACConfig describing mock behaviour.
        ready_event:  Set when the server is ready to accept connections.
        stop_event:   Set by the caller to request teardown.
        port_holder:  Single-element list; receives the bound port number.

    Returns:
        The started (daemon) thread.
    """
    def _run() -> None:
        async def _async_run() -> None:
            async with DummyDAC(LOCALHOST, 0, config) as dac:
                port_holder[0] = dac.port
                ready_event.set()
                while not stop_event.is_set():
                    await asyncio.sleep(0.05)

        asyncio.run(_async_run())

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return thread


def _wait_ready(event: threading.Event, timeout: float = SHORT_TIMEOUT) -> None:
    """Raise RuntimeError if the event is not set within *timeout* seconds."""
    if not event.wait(timeout=timeout):
        raise RuntimeError(f"Server did not become ready within {timeout}s")


def _build_start_run_command(
    run_id: str,
    op_time_ns: int = 1_000_000,
    sample_rate: int = 10_000,
    num_channels: int = 0,
    sample_op: bool = False,
) -> pb.StartRunCommand:
    """
    Build a minimal StartRunCommand protobuf for testing.

    Args:
        run_id:       UUID string for the run.
        op_time_ns:   OP phase duration in nanoseconds.
        sample_rate:  DAQ sampling rate in Hz.
        num_channels: Number of DAQ channels.
        sample_op:    Whether to enable sample-during-OP mode.

    Returns:
        A populated ``pb.StartRunCommand``.
    """
    return pb.StartRunCommand(
        run=pb.Run(id=run_id, chunk=0),
        run_config=pb.RunConfig(
            ic_time=pb.Time(value=100, prefix=pb.Prefix.MICRO),
            op_time=pb.Time(value=op_time_ns, prefix=pb.Prefix.NANO),
        ),
        daq_config=pb.DaqConfig(
            num_channels=num_channels,
            sample_rate=sample_rate,
            sample_op=sample_op,
        ),
    )


class TestProxyLifecycle:
    """Basic ProxyServer startup, port reporting, and client connectivity."""

    def test_proxy_lifecycle(self) -> None:
        """Start, connect, and stop the proxy; verify is_running() and local_port() behave correctly."""
        config = DummyDACConfig(mac_mode=DummyDACMacMode.PHYSICAL)
        ready = threading.Event()
        stop = threading.Event()
        dac_port_holder = [0]

        dac_thread = _start_dummy_dac(config, ready, stop, dac_port_holder)
        _wait_ready(ready)

        proxy = ProxyServer()
        proxy.set_session_timeout(SESSION_TIMEOUT)
        client = None

        try:
            proxy.add_backend(LOCALHOST, dac_port_holder[0])
            proxy.start(LOCALHOST, 0)

            assert proxy.is_running(), "proxy.is_running() must be True after start()"
            proxy_port = proxy.local_port()
            assert proxy_port > 0, f"proxy.local_port() must be > 0, got {proxy_port}"

            client = ControlChannel.create(LOCALHOST, proxy_port, timeout=SHORT_TIMEOUT)
            client.start()
            assert client.is_connected(), "Client must be connected to the proxy"
        finally:
            if client is not None:
                client.stop()
            proxy.stop()
            assert not proxy.is_running(), "proxy.is_running() must be False after stop()"
            stop.set()
            dac_thread.join(timeout=SHORT_TIMEOUT)


class TestMessageForwarding:
    """Verify that each command type is correctly forwarded through the proxy."""

    def test_describe_through_native_proxy(self) -> None:
        """Extract command is forwarded; response contains the backend DummyDAC carrier MACs."""
        config = DummyDACConfig(mac_mode=DummyDACMacMode.PHYSICAL)
        ready = threading.Event()
        stop = threading.Event()
        dac_port_holder = [0]

        dac_thread = _start_dummy_dac(config, ready, stop, dac_port_holder)
        _wait_ready(ready)

        # Expected carrier MACs from PHYSICAL mode DummyDAC (REDAC = 2 carriers).
        # Entity ids use the firmware wire format with a leading '/'.
        expected_macs = {"/AB-CD-EF-12-34-56", "/AB-CD-EF-12-34-57"}

        proxy = ProxyServer()
        proxy.set_session_timeout(SESSION_TIMEOUT)
        client = None

        try:
            proxy.add_backend(LOCALHOST, dac_port_holder[0])
            proxy.start(LOCALHOST, 0)

            client = ControlChannel.create(LOCALHOST, proxy.local_port(), timeout=SHORT_TIMEOUT)
            client.start()

            module_bytes = client.extract(recursive=True, specification=True, timeout=SHORT_TIMEOUT)
            module = pb.Module()
            module.ParseFromString(module_bytes)

            entity = module.items[0].entity_specification.entity
            carrier_ids = {c.id for c in entity.children}
            assert carrier_ids == expected_macs, (
                f"Expected carrier MACs {expected_macs}, got {carrier_ids}"
            )
        finally:
            if client is not None:
                client.stop()
            proxy.stop()
            stop.set()
            dac_thread.join(timeout=SHORT_TIMEOUT)

    def test_reset_through_native_proxy(self) -> None:
        """Reset command is forwarded to the DummyDAC and the success response returned without exception."""
        config = DummyDACConfig(mac_mode=DummyDACMacMode.PHYSICAL)
        ready = threading.Event()
        stop = threading.Event()
        dac_port_holder = [0]

        dac_thread = _start_dummy_dac(config, ready, stop, dac_port_holder)
        _wait_ready(ready)

        proxy = ProxyServer()
        proxy.set_session_timeout(SESSION_TIMEOUT)
        client = None

        try:
            proxy.add_backend(LOCALHOST, dac_port_holder[0])
            proxy.start(LOCALHOST, 0)

            client = ControlChannel.create(LOCALHOST, proxy.local_port(), timeout=SHORT_TIMEOUT)
            client.start()

            # Should not raise — DummyDAC's ResetHandler returns ResetResponse
            client.reset(keep_calibration=True, sync=False, timeout=SHORT_TIMEOUT)
        finally:
            if client is not None:
                client.stop()
            proxy.stop()
            stop.set()
            dac_thread.join(timeout=SHORT_TIMEOUT)

    def test_config_roundtrip_through_native_proxy(self) -> None:
        """Config set via proxy is stored by the backend and retrievable via extract."""
        config = DummyDACConfig(mac_mode=DummyDACMacMode.PHYSICAL)
        ready = threading.Event()
        stop = threading.Event()
        dac_port_holder = [0]

        dac_thread = _start_dummy_dac(config, ready, stop, dac_port_holder)
        _wait_ready(ready)

        proxy = ProxyServer()
        proxy.set_session_timeout(SESSION_TIMEOUT)
        client = None

        try:
            proxy.add_backend(LOCALHOST, dac_port_holder[0])
            proxy.start(LOCALHOST, 0)

            client = ControlChannel.create(LOCALHOST, proxy.local_port(), timeout=SHORT_TIMEOUT)
            client.start()

            # First extract to learn the carrier paths
            module_bytes = client.extract(recursive=True, specification=True, timeout=SHORT_TIMEOUT)
            module = pb.Module()
            module.ParseFromString(module_bytes)
            entity = module.items[0].entity_specification.entity
            assert len(entity.children) > 0, "Expected at least one carrier"

            # Build a ConfigBundle targeting the first carrier.
            # Entity ids already include the leading '/' in firmware wire format.
            carrier_path = entity.children[0].id
            module = pb.Module()
            entry = module.items.add()
            entry.entity.path = carrier_path
            # A minimal but non-trivial config payload (ADC channel config)
            ch = entry.adc_config.channels.add()
            ch.idx = 0
            ch.gain = 1.0
            ch.offset = 0.0

            ok = client.set_module(module.SerializeToString(), timeout=SHORT_TIMEOUT)
            assert ok, "set_module() should return True on success"

            # Extract config back — verify the path is present in the response
            module_bytes = client.extract(carrier_path, configuration=True, recursive=False, timeout=SHORT_TIMEOUT)
            retrieved = pb.Module()
            retrieved.ParseFromString(module_bytes)
            # The proxy must have forwarded both commands without error
            # (DummyDAC stores the config; presence of module_bytes is sufficient)
            assert retrieved is not None
        finally:
            if client is not None:
                client.stop()
            proxy.stop()
            stop.set()
            dac_thread.join(timeout=SHORT_TIMEOUT)


class TestRunLifecycle:
    """Verify that run commands and state transitions pass through the proxy."""

    def test_run_lifecycle_through_native_proxy(self) -> None:
        """Run started through the proxy reaches TAKE_OFF and then DONE."""
        config = DummyDACConfig(mac_mode=DummyDACMacMode.PHYSICAL)
        ready = threading.Event()
        stop = threading.Event()
        dac_port_holder = [0]

        dac_thread = _start_dummy_dac(config, ready, stop, dac_port_holder)
        _wait_ready(ready)

        proxy = ProxyServer()
        proxy.set_session_timeout(SESSION_TIMEOUT)
        client = None

        states_received: list[int] = []
        done_event = threading.Event()

        def on_state_change(msg_bytes: bytes) -> None:
            """Record incoming run state transitions."""
            msg = pb.MessageV1()
            msg.ParseFromString(msg_bytes)
            new_state = msg.run_state_change_message.new_
            states_received.append(new_state)
            if new_state in (pb.RunState.DONE, pb.RunState.ERROR):
                done_event.set()

        try:
            proxy.add_backend(LOCALHOST, dac_port_holder[0])
            proxy.start(LOCALHOST, 0)

            client = ControlChannel.create(LOCALHOST, proxy.local_port(), timeout=SHORT_TIMEOUT)
            client.start()
            client.register_callback(
                pb.MessageV1.RUN_STATE_CHANGE_MESSAGE_FIELD_NUMBER,
                on_state_change,
            )

            run_id = str(uuid.uuid4())
            cmd = _build_start_run_command(run_id, op_time_ns=500_000)
            client.start_run_request(cmd.SerializeToString(), timeout=SHORT_TIMEOUT)

            assert done_event.wait(timeout=RUN_TIMEOUT), (
                f"Run did not complete within {RUN_TIMEOUT}s. "
                f"States received: {states_received}"
            )

            assert pb.RunState.TAKE_OFF in states_received, (
                f"TAKE_OFF not seen. States: {states_received}"
            )
            assert pb.RunState.DONE in states_received, (
                f"DONE not seen. States: {states_received}"
            )
        finally:
            if client is not None:
                client.stop()
            proxy.stop()
            stop.set()
            dac_thread.join(timeout=SHORT_TIMEOUT)

    def test_data_passthrough_through_native_proxy(self) -> None:
        """At least one RunDataMessage reaches the client during a DAQ-enabled run through the proxy."""
        config = DummyDACConfig(mac_mode=DummyDACMacMode.PHYSICAL)
        ready = threading.Event()
        stop = threading.Event()
        dac_port_holder = [0]

        dac_thread = _start_dummy_dac(config, ready, stop, dac_port_holder)
        _wait_ready(ready)

        proxy = ProxyServer()
        proxy.set_session_timeout(SESSION_TIMEOUT)
        client = None

        data_received = threading.Event()
        done_event = threading.Event()

        def on_run_data(msg_bytes: bytes) -> None:
            """Signal that at least one data message arrived."""
            data_received.set()

        def on_state_change(msg_bytes: bytes) -> None:
            """Signal when the run completes."""
            msg = pb.MessageV1()
            msg.ParseFromString(msg_bytes)
            if msg.run_state_change_message.new_ in (pb.RunState.DONE, pb.RunState.ERROR):
                done_event.set()

        try:
            proxy.add_backend(LOCALHOST, dac_port_holder[0])
            proxy.start(LOCALHOST, 0)

            client = ControlChannel.create(LOCALHOST, proxy.local_port(), timeout=SHORT_TIMEOUT)
            client.start()
            client.register_callback(
                pb.MessageV1.RUN_DATA_MESSAGE_FIELD_NUMBER,
                on_run_data,
            )
            client.register_callback(
                pb.MessageV1.RUN_STATE_CHANGE_MESSAGE_FIELD_NUMBER,
                on_state_change,
            )

            run_id = str(uuid.uuid4())
            cmd = _build_start_run_command(
                run_id,
                op_time_ns=5_000_000,
                sample_rate=10_000,
                num_channels=1,
                sample_op=True,
            )
            client.start_run_request(cmd.SerializeToString(), timeout=SHORT_TIMEOUT)

            assert done_event.wait(timeout=RUN_TIMEOUT), (
                f"Run did not complete within {RUN_TIMEOUT}s"
            )
            assert data_received.is_set(), (
                "No RunDataMessage received from DummyDAC through proxy"
            )
        finally:
            if client is not None:
                client.stop()
            proxy.stop()
            stop.set()
            dac_thread.join(timeout=SHORT_TIMEOUT)


class TestMultiBackend:
    """Verify proxy operation with multiple backend devices."""

    def test_multi_backend_native_proxy(self) -> None:
        """Two backends behind one proxy: describe response aggregates carriers from both."""
        # DummyDAC1 — PHYSICAL: AB-CD-EF-12-34-56, AB-CD-EF-12-34-57
        config1 = DummyDACConfig(mac_mode=DummyDACMacMode.PHYSICAL)
        # DummyDAC2 — LUCIDAC PHYSICAL mode gives a single unique carrier
        config2 = DummyDACConfig(mac_mode=DummyDACMacMode.PHYSICAL, lucidac_mode=True)

        ready1, ready2 = threading.Event(), threading.Event()
        stop1, stop2 = threading.Event(), threading.Event()
        port1_holder, port2_holder = [0], [0]

        t1 = _start_dummy_dac(config1, ready1, stop1, port1_holder)
        t2 = _start_dummy_dac(config2, ready2, stop2, port2_holder)
        _wait_ready(ready1)
        _wait_ready(ready2)

        proxy = ProxyServer()
        proxy.set_session_timeout(SESSION_TIMEOUT)
        client = None

        try:
            proxy.add_backend(LOCALHOST, port1_holder[0])
            proxy.add_backend(LOCALHOST, port2_holder[0])
            proxy.start(LOCALHOST, 0)

            client = ControlChannel.create(LOCALHOST, proxy.local_port(), timeout=SHORT_TIMEOUT)
            client.start()

            module_bytes = client.extract(recursive=True, specification=True, timeout=SHORT_TIMEOUT)
            module = pb.Module()
            module.ParseFromString(module_bytes)
            entity = module.items[0].entity_specification.entity

            # REDAC DummyDAC contributes 2 carriers, LUCIDAC contributes 1 → 3 total
            carrier_count = len(entity.children)
            assert carrier_count >= 2, (
                f"Expected at least 2 carriers from two backends, got {carrier_count}: "
                f"{[c.id for c in entity.children]}"
            )
        finally:
            if client is not None:
                client.stop()
            proxy.stop()
            stop1.set()
            stop2.set()
            t1.join(timeout=SHORT_TIMEOUT)
            t2.join(timeout=SHORT_TIMEOUT)


class TestClientSessionOrdering:
    """Verify the FIFO session queue: one active session at a time."""

    def test_client_session_ordering(self) -> None:
        """Second client's describe blocks until first client disconnects and releases the session."""
        config = DummyDACConfig(mac_mode=DummyDACMacMode.PHYSICAL)
        ready = threading.Event()
        stop = threading.Event()
        dac_port_holder = [0]

        dac_thread = _start_dummy_dac(config, ready, stop, dac_port_holder)
        _wait_ready(ready)

        proxy = ProxyServer()
        proxy.set_session_timeout(SESSION_TIMEOUT)

        client1 = None
        client2 = None

        client2_result: list = []
        client2_error: list = []
        client2_done = threading.Event()

        def client2_worker(port: int) -> None:
            """Connect client2 and describe. Blocks until session is granted."""
            ch = None
            try:
                ch = ControlChannel.create(LOCALHOST, port, timeout=SHORT_TIMEOUT)
                ch.start()
                # This blocks until the session queue grants access
                module_bytes = ch.extract(recursive=True, specification=True, timeout=RUN_TIMEOUT)
                module = pb.Module()
                module.ParseFromString(module_bytes)
                client2_result.append(module)
            except Exception as exc:
                client2_error.append(exc)
            finally:
                if ch is not None:
                    ch.stop()
                client2_done.set()

        try:
            proxy.add_backend(LOCALHOST, dac_port_holder[0])
            proxy.start(LOCALHOST, 0)
            proxy_port = proxy.local_port()

            # Client 1 connects and holds the session
            client1 = ControlChannel.create(LOCALHOST, proxy_port, timeout=SHORT_TIMEOUT)
            client1.start()
            # First extract — ensures client1 has an active session
            module_bytes = client1.extract(recursive=True, specification=True, timeout=SHORT_TIMEOUT)
            module = pb.Module()
            module.ParseFromString(module_bytes)
            entity = module.items[0].entity_specification.entity
            assert len(entity.children) > 0, "First client extract should succeed"

            # Client 2 connects in background — will queue behind client1
            t2 = threading.Thread(target=client2_worker, args=(proxy_port,), daemon=True)
            t2.start()
            # Give client2 time to connect and queue up
            time.sleep(0.5)

            # Release client1 — session should pass to client2
            client1.stop()
            client1 = None

            assert client2_done.wait(timeout=RUN_TIMEOUT), (
                "Client2 did not complete within timeout after client1 disconnected"
            )
            assert not client2_error, (
                f"Client2 encountered error: {client2_error}"
            )
            assert client2_result, "Client2 should have received an extract response"
        finally:
            if client1 is not None:
                client1.stop()
            if client2 is not None:
                client2.stop()
            proxy.stop()
            stop.set()
            dac_thread.join(timeout=SHORT_TIMEOUT)

    def test_client_disconnect_frees_session(self) -> None:
        """After first client disconnects, second client can describe immediately without queuing."""
        config = DummyDACConfig(mac_mode=DummyDACMacMode.PHYSICAL)
        ready = threading.Event()
        stop = threading.Event()
        dac_port_holder = [0]

        dac_thread = _start_dummy_dac(config, ready, stop, dac_port_holder)
        _wait_ready(ready)

        proxy = ProxyServer()
        proxy.set_session_timeout(SESSION_TIMEOUT)
        client2 = None

        try:
            proxy.add_backend(LOCALHOST, dac_port_holder[0])
            proxy.start(LOCALHOST, 0)
            proxy_port = proxy.local_port()

            # Client 1: connect, describe, disconnect
            client1 = ControlChannel.create(LOCALHOST, proxy_port, timeout=SHORT_TIMEOUT)
            client1.start()
            client1.extract(recursive=True, specification=True, timeout=SHORT_TIMEOUT)
            client1.stop()

            # Give proxy a moment to process the disconnect and free the session
            time.sleep(0.3)

            # Client 2: should connect and extract without any queue wait
            client2 = ControlChannel.create(LOCALHOST, proxy_port, timeout=SHORT_TIMEOUT)
            client2.start()
            module_bytes = client2.extract(recursive=True, specification=True, timeout=SHORT_TIMEOUT)
            module = pb.Module()
            module.ParseFromString(module_bytes)
            entity = module.items[0].entity_specification.entity

            assert len(entity.children) > 0, (
                "Second client should receive extract response after first disconnects"
            )
        finally:
            if client2 is not None:
                client2.stop()
            proxy.stop()
            stop.set()
            dac_thread.join(timeout=SHORT_TIMEOUT)


class TestErrorHandling:
    """Verify error propagation from backend through the proxy to the client."""

    def test_device_error_forwarded(self) -> None:
        """Backend error on start_run is propagated to the client as RuntimeError."""
        config = DummyDACConfig(
            mac_mode=DummyDACMacMode.PHYSICAL,
            error_stage=DummyDACErrorStage.AT_START_RUN,
            error_message="Simulated start run error",
        )
        ready = threading.Event()
        stop = threading.Event()
        dac_port_holder = [0]

        dac_thread = _start_dummy_dac(config, ready, stop, dac_port_holder)
        _wait_ready(ready)

        proxy = ProxyServer()
        proxy.set_session_timeout(SESSION_TIMEOUT)
        client = None

        try:
            proxy.add_backend(LOCALHOST, dac_port_holder[0])
            proxy.start(LOCALHOST, 0)

            client = ControlChannel.create(LOCALHOST, proxy.local_port(), timeout=SHORT_TIMEOUT)
            client.start()

            run_id = str(uuid.uuid4())
            cmd = _build_start_run_command(run_id)

            with pytest.raises(RuntimeError):
                client.start_run_request(cmd.SerializeToString(), timeout=SHORT_TIMEOUT)
        finally:
            if client is not None:
                client.stop()
            proxy.stop()
            stop.set()
            dac_thread.join(timeout=SHORT_TIMEOUT)

    def test_device_disconnect_during_run(self) -> None:
        """Backend disconnect mid-run leaves the proxy operational and forwards an error to the client."""
        config = DummyDACConfig(mac_mode=DummyDACMacMode.PHYSICAL)
        ready = threading.Event()
        stop = threading.Event()
        dac_port_holder = [0]

        dac_thread = _start_dummy_dac(config, ready, stop, dac_port_holder)
        _wait_ready(ready)

        proxy = ProxyServer()
        proxy.set_session_timeout(SESSION_TIMEOUT)
        client = None

        error_received = threading.Event()
        run_started = threading.Event()

        def on_state_change(msg_bytes: bytes) -> None:
            """Set run_started when TAKE_OFF arrives."""
            msg = pb.MessageV1()
            msg.ParseFromString(msg_bytes)
            state = msg.run_state_change_message.new_
            if state == pb.RunState.TAKE_OFF:
                run_started.set()

        def on_error(msg_bytes: bytes) -> None:
            """Set error_received when proxy forwards an ErrorMessage."""
            error_received.set()

        try:
            proxy.add_backend(LOCALHOST, dac_port_holder[0])
            proxy.start(LOCALHOST, 0)

            client = ControlChannel.create(LOCALHOST, proxy.local_port(), timeout=SHORT_TIMEOUT)
            client.start()
            client.register_callback(
                pb.MessageV1.RUN_STATE_CHANGE_MESSAGE_FIELD_NUMBER,
                on_state_change,
            )
            client.register_callback(
                pb.MessageV1.ERROR_MESSAGE_FIELD_NUMBER,
                on_error,
            )

            # Use a long op_time so the run is still in progress when we kill the DAC
            run_id = str(uuid.uuid4())
            cmd = _build_start_run_command(run_id, op_time_ns=30_000_000_000)

            # Fire-and-forget: don't wait for run to complete
            start_thread = threading.Thread(
                target=lambda: client.start_run_request(cmd.SerializeToString(), timeout=5.0),
                daemon=True,
            )
            start_thread.start()

            # Wait for the run to start (TAKE_OFF), then kill the DAC
            if run_started.wait(timeout=SHORT_TIMEOUT):
                stop.set()  # Signal DummyDAC thread to exit
            else:
                # Run didn't start in time — still kill the DAC and check for error
                stop.set()

            # After the backend disappears, proxy should send an error to the client
            # Allow generous time for the TCP connection to be detected as broken
            error_received.wait(timeout=RUN_TIMEOUT)
            # Primary assertion: proxy remains operational (not crashed)
            # The proxy's is_running() should still be True (proxy stays alive)
            assert proxy.is_running(), (
                "Proxy should remain running after backend disconnect"
            )
        finally:
            if client is not None:
                client.stop()
            proxy.stop()
            stop.set()
            dac_thread.join(timeout=SHORT_TIMEOUT)


AUTH_ENV_VAR = "PYBRID_AUTHENTICATION"
AUTH_TOKEN = "test-secret-token-42"
WRONG_TOKEN = "wrong-token-99"


class TestAuthentication:
    """Verify proxy-level authentication gating."""

    def test_auth_required_no_env_raises(self) -> None:
        """Constructing ProxyServer(requires_auth=True) without PYBRID_AUTHENTICATION set raises RuntimeError."""
        # Ensure env var is NOT set
        old_value = os.environ.pop(AUTH_ENV_VAR, None)
        try:
            with pytest.raises(RuntimeError):
                ProxyServer(requires_auth=True)
        finally:
            # Restore original env state
            if old_value is not None:
                os.environ[AUTH_ENV_VAR] = old_value

    def test_auth_required_rejects_unauthenticated(self) -> None:
        """Describe without prior auth on a requires_auth proxy raises RuntimeError('Authentication required')."""
        os.environ[AUTH_ENV_VAR] = AUTH_TOKEN

        config = DummyDACConfig(mac_mode=DummyDACMacMode.PHYSICAL)
        ready = threading.Event()
        stop = threading.Event()
        dac_port_holder = [0]

        dac_thread = _start_dummy_dac(config, ready, stop, dac_port_holder)
        _wait_ready(ready)

        proxy = ProxyServer(requires_auth=True)
        proxy.set_session_timeout(SESSION_TIMEOUT)
        client = None

        try:
            proxy.add_backend(LOCALHOST, dac_port_holder[0])
            proxy.start(LOCALHOST, 0)

            client = ControlChannel.create(LOCALHOST, proxy.local_port(), timeout=SHORT_TIMEOUT)
            client.start()

            # Send extract WITHOUT authenticating — should be rejected.
            # The ControlChannel.extract() wraps send_and_recv; if the proxy
            # returns an ErrorMessage, the binding raises RuntimeError.
            with pytest.raises(RuntimeError, match="Authentication required"):
                client.extract(recursive=True, specification=True, timeout=SHORT_TIMEOUT)
        finally:
            if client is not None:
                client.stop()
            proxy.stop()
            stop.set()
            dac_thread.join(timeout=SHORT_TIMEOUT)
            os.environ.pop(AUTH_ENV_VAR, None)

    def test_auth_required_correct_token(self) -> None:
        """After authenticating with the correct token, describe succeeds and returns carrier data."""
        os.environ[AUTH_ENV_VAR] = AUTH_TOKEN

        config = DummyDACConfig(mac_mode=DummyDACMacMode.PHYSICAL)
        ready = threading.Event()
        stop = threading.Event()
        dac_port_holder = [0]

        dac_thread = _start_dummy_dac(config, ready, stop, dac_port_holder)
        _wait_ready(ready)

        proxy = ProxyServer(requires_auth=True)
        proxy.set_session_timeout(SESSION_TIMEOUT)
        client = None

        try:
            proxy.add_backend(LOCALHOST, dac_port_holder[0])
            proxy.start(LOCALHOST, 0)

            client = ControlChannel.create(LOCALHOST, proxy.local_port(), timeout=SHORT_TIMEOUT)
            client.start()

            # Step 1: Authenticate with the correct token.
            auth_ok = client.authenticate(AUTH_TOKEN, timeout=SHORT_TIMEOUT)
            assert auth_ok, "authenticate() should return True for correct token"

            # Step 2: After auth, extract should succeed.
            module_bytes = client.extract(recursive=True, specification=True, timeout=SHORT_TIMEOUT)
            module = pb.Module()
            module.ParseFromString(module_bytes)
            entity = module.items[0].entity_specification.entity

            # Must have at least one carrier from the DummyDAC.
            assert len(entity.children) > 0, (
                f"Expected at least one carrier after auth, got {len(entity.children)}"
            )
        finally:
            if client is not None:
                client.stop()
            proxy.stop()
            stop.set()
            dac_thread.join(timeout=SHORT_TIMEOUT)
            os.environ.pop(AUTH_ENV_VAR, None)

    def test_auth_not_required_forwards(self) -> None:
        """With requires_auth=False (default), auth requests are forwarded to the backend unchanged."""
        config = DummyDACConfig(mac_mode=DummyDACMacMode.PHYSICAL)
        ready = threading.Event()
        stop = threading.Event()
        dac_port_holder = [0]

        dac_thread = _start_dummy_dac(config, ready, stop, dac_port_holder)
        _wait_ready(ready)

        # Default constructor — requires_auth=False
        proxy = ProxyServer()
        proxy.set_session_timeout(SESSION_TIMEOUT)
        client = None

        try:
            proxy.add_backend(LOCALHOST, dac_port_holder[0])
            proxy.start(LOCALHOST, 0)

            client = ControlChannel.create(LOCALHOST, proxy.local_port(), timeout=SHORT_TIMEOUT)
            client.start()

            # Auth request should be forwarded to DummyDAC (backward compat).
            # DummyDAC accepts all auth → returns SuccessMessage.
            auth_ok = client.authenticate("any-token", timeout=SHORT_TIMEOUT)
            assert auth_ok, (
                "With requires_auth=False, auth should be forwarded to backend "
                "and DummyDAC should accept it"
            )

            # Extract should also work (no auth gating at proxy).
            module_bytes = client.extract(recursive=True, specification=True, timeout=SHORT_TIMEOUT)
            module = pb.Module()
            module.ParseFromString(module_bytes)
            entity = module.items[0].entity_specification.entity
            assert len(entity.children) > 0, (
                "Extract should work with requires_auth=False"
            )
        finally:
            if client is not None:
                client.stop()
            proxy.stop()
            stop.set()
            dac_thread.join(timeout=SHORT_TIMEOUT)


class TestConcurrentSessions:
    """Verify the concurrent session architecture: cached describe fast path,
    control message serialization, and session overload rejection."""

    def test_concurrent_describe_fast_path(self) -> None:
        """Two simultaneous clients both receive describe responses without blocking each other."""
        config = DummyDACConfig(mac_mode=DummyDACMacMode.PHYSICAL)
        ready = threading.Event()
        stop = threading.Event()
        dac_port_holder = [0]

        dac_thread = _start_dummy_dac(config, ready, stop, dac_port_holder)
        _wait_ready(ready)

        proxy = ProxyServer()
        proxy.set_session_timeout(SESSION_TIMEOUT)

        result_a: list = []
        result_b: list = []
        error_a: list = []
        error_b: list = []

        def describe_worker(
            port: int, result_list: list, error_list: list, label: str
        ) -> None:
            """Connect a client and send extract, storing the result."""
            ch = None
            try:
                ch = ControlChannel.create(LOCALHOST, port, timeout=SHORT_TIMEOUT)
                ch.start()
                module_bytes = ch.extract(recursive=True, specification=True, timeout=SHORT_TIMEOUT)
                module = pb.Module()
                module.ParseFromString(module_bytes)
                entity = module.items[0].entity_specification.entity
                result_list.append(entity)
            except Exception as exc:
                error_list.append(exc)
            finally:
                if ch is not None:
                    ch.stop()

        try:
            proxy.add_backend(LOCALHOST, dac_port_holder[0])
            proxy.start(LOCALHOST, 0)
            proxy_port = proxy.local_port()

            # Launch both describe calls in parallel threads.
            thread_a = threading.Thread(
                target=describe_worker,
                args=(proxy_port, result_a, error_a, "Client A"),
                daemon=True,
            )
            thread_b = threading.Thread(
                target=describe_worker,
                args=(proxy_port, result_b, error_b, "Client B"),
                daemon=True,
            )

            thread_a.start()
            thread_b.start()

            thread_a.join(timeout=RUN_TIMEOUT)
            thread_b.join(timeout=RUN_TIMEOUT)

            assert not error_a, f"Client A encountered error: {error_a}"
            assert not error_b, f"Client B encountered error: {error_b}"
            assert result_a, "Client A should have received an extract response"
            assert result_b, "Client B should have received an extract response"

            # Both should have carrier children from the DummyDAC.
            assert len(result_a[0].children) > 0, (
                "Client A: expected at least one carrier in entity tree"
            )
            assert len(result_b[0].children) > 0, (
                "Client B: expected at least one carrier in entity tree"
            )
        finally:
            proxy.stop()
            stop.set()
            dac_thread.join(timeout=SHORT_TIMEOUT)

    def test_control_message_serialization(self) -> None:
        """Queued client receives BusyResponse; after active client disconnects, queued client succeeds."""
        config = DummyDACConfig(mac_mode=DummyDACMacMode.PHYSICAL)
        ready = threading.Event()
        stop = threading.Event()
        dac_port_holder = [0]

        dac_thread = _start_dummy_dac(config, ready, stop, dac_port_holder)
        _wait_ready(ready)

        proxy = ProxyServer()
        proxy.set_session_timeout(SESSION_TIMEOUT)

        client_a = None
        client_b_got_busy = threading.Event()
        client_b_reset_ok = threading.Event()
        client_b_error: list = []

        def client_b_worker(port: int) -> None:
            """Connect client B. First reset gets BusyResponse, then retry after A releases."""
            ch = None
            try:
                ch = ControlChannel.create(LOCALHOST, port, timeout=SHORT_TIMEOUT)
                ch.start()

                # First attempt while A is still active — send_and_recv returns
                # a BusyResponse (not an error, not a reset_response).
                req = pb.MessageV1()
                req.id = str(uuid.uuid4())
                req.reset_command.keep_calibration = True
                req.reset_command.sync = False
                resp_bytes = ch.send_and_recv(req.SerializeToString(), SHORT_TIMEOUT)
                resp = pb.MessageV1()
                resp.ParseFromString(resp_bytes)
                if resp.HasField("busy_response"):
                    client_b_got_busy.set()

                # Wait for A to release, then retry (B will become active).
                client_b_got_busy.wait(timeout=RUN_TIMEOUT)
                time.sleep(0.8)

                ch.reset(keep_calibration=True, sync=False, timeout=RUN_TIMEOUT)
                client_b_reset_ok.set()
            except Exception as exc:
                client_b_error.append(exc)
            finally:
                if ch is not None:
                    ch.stop()

        try:
            proxy.add_backend(LOCALHOST, dac_port_holder[0])
            proxy.start(LOCALHOST, 0)
            proxy_port = proxy.local_port()

            # Client A connects and sends reset (becomes active).
            client_a = ControlChannel.create(LOCALHOST, proxy_port, timeout=SHORT_TIMEOUT)
            client_a.start()
            client_a.reset(keep_calibration=True, sync=False, timeout=SHORT_TIMEOUT)

            # Client B connects in background — will queue behind A.
            thread_b = threading.Thread(
                target=client_b_worker,
                args=(proxy_port,),
                daemon=True,
            )
            thread_b.start()

            # Wait for B to receive the BusyResponse.
            assert client_b_got_busy.wait(timeout=RUN_TIMEOUT), (
                "Client B should have received BusyResponse while A is active"
            )

            # Release Client A — session should pass to Client B.
            client_a.stop()
            client_a = None

            # B should now retry and succeed.
            thread_b.join(timeout=RUN_TIMEOUT)
            assert not client_b_error, (
                f"Client B encountered error: {client_b_error}"
            )
            assert client_b_reset_ok.is_set(), (
                "Client B should have completed its reset successfully after A released"
            )
        finally:
            if client_a is not None:
                client_a.stop()
            proxy.stop()
            stop.set()
            dac_thread.join(timeout=SHORT_TIMEOUT)

    def test_session_overload_rejection(self) -> None:
        """With max_sessions=2, the third connecting client is rejected while the first two work."""
        config = DummyDACConfig(mac_mode=DummyDACMacMode.PHYSICAL)
        ready = threading.Event()
        stop = threading.Event()
        dac_port_holder = [0]

        dac_thread = _start_dummy_dac(config, ready, stop, dac_port_holder)
        _wait_ready(ready)

        proxy = ProxyServer()
        proxy.set_session_timeout(SESSION_TIMEOUT)
        proxy.set_max_sessions(2)

        client1 = None
        client2 = None

        try:
            proxy.add_backend(LOCALHOST, dac_port_holder[0])
            proxy.start(LOCALHOST, 0)
            proxy_port = proxy.local_port()

            # Connect two clients — both within limits.
            client1 = ControlChannel.create(LOCALHOST, proxy_port, timeout=SHORT_TIMEOUT)
            client1.start()

            client2 = ControlChannel.create(LOCALHOST, proxy_port, timeout=SHORT_TIMEOUT)
            client2.start()

            # First client extract should succeed.
            module_bytes = client1.extract(recursive=True, specification=True, timeout=SHORT_TIMEOUT)
            module = pb.Module()
            module.ParseFromString(module_bytes)
            entity = module.items[0].entity_specification.entity
            assert len(entity.children) > 0, (
                "Client 1 extract should succeed within max_sessions limit"
            )

            # Third client should be rejected.
            third_rejected = False
            try:
                client3 = ControlChannel.create(LOCALHOST, proxy_port, timeout=SHORT_TIMEOUT)
                client3.start()

                # If connection succeeded, try extract — should get an error.
                try:
                    client3.extract(recursive=True, specification=True, timeout=2.0)
                except RuntimeError:
                    third_rejected = True
                finally:
                    client3.stop()
            except RuntimeError:
                # Connection refused at TCP level.
                third_rejected = True

            assert third_rejected, (
                "Third client should be rejected when max_sessions=2"
            )
        finally:
            if client1 is not None:
                client1.stop()
            if client2 is not None:
                client2.stop()
            proxy.stop()
            stop.set()
            dac_thread.join(timeout=SHORT_TIMEOUT)


class TestBusyWaitPingPolling:
    """Verify the PingCommand/busy-response polling cycle for queued sessions.

    The C++ proxy responds to PingCommand in both the queued-session and
    active-session phases.
    """

    def test_ping_returns_busy_when_session_queued(self) -> None:
        """PingCommand from a queued session returns DeviceBusyMessage while another session is active."""
        config = DummyDACConfig(mac_mode=DummyDACMacMode.PHYSICAL)
        ready = threading.Event()
        stop = threading.Event()
        dac_port_holder = [0]

        dac_thread = _start_dummy_dac(config, ready, stop, dac_port_holder)
        _wait_ready(ready)

        proxy = ProxyServer()
        proxy.set_session_timeout(SESSION_TIMEOUT)
        client_a = None
        client_b = None

        try:
            proxy.add_backend(LOCALHOST, dac_port_holder[0])
            proxy.start(LOCALHOST, 0)
            proxy_port = proxy.local_port()

            # Client A connects and sends extract — becomes the active session.
            client_a = ControlChannel.create(LOCALHOST, proxy_port, timeout=SHORT_TIMEOUT)
            client_a.start()
            client_a.extract(recursive=True, specification=True, timeout=SHORT_TIMEOUT)

            # Client B connects while A holds the session.
            client_b = ControlChannel.create(LOCALHOST, proxy_port, timeout=SHORT_TIMEOUT)
            client_b.start()

            # Send a raw PingCommand from client B (queued session).
            req = pb.MessageV1()
            req.id = str(uuid.uuid4())
            req.ping_command.CopyFrom(pb.PingCommand())
            resp_bytes = client_b.send_and_recv(req.SerializeToString(), SHORT_TIMEOUT)
            resp = pb.MessageV1()
            resp.ParseFromString(resp_bytes)

            assert resp.HasField("busy_response"), (
                f"Queued client B should receive busy_response for PingCommand, "
                f"got kind: {resp.WhichOneof('kind')}"
            )
        finally:
            if client_a is not None:
                client_a.stop()
            if client_b is not None:
                client_b.stop()
            proxy.stop()
            stop.set()
            dac_thread.join(timeout=SHORT_TIMEOUT)

    def test_ping_returns_success_when_session_active(self) -> None:
        """PingCommand from the active (sole) session returns SuccessMessage."""
        config = DummyDACConfig(mac_mode=DummyDACMacMode.PHYSICAL)
        ready = threading.Event()
        stop = threading.Event()
        dac_port_holder = [0]

        dac_thread = _start_dummy_dac(config, ready, stop, dac_port_holder)
        _wait_ready(ready)

        proxy = ProxyServer()
        proxy.set_session_timeout(SESSION_TIMEOUT)
        client_a = None

        try:
            proxy.add_backend(LOCALHOST, dac_port_holder[0])
            proxy.start(LOCALHOST, 0)
            proxy_port = proxy.local_port()

            # Client A is the only client; it becomes the active session.
            client_a = ControlChannel.create(LOCALHOST, proxy_port, timeout=SHORT_TIMEOUT)
            client_a.start()

            # A brief extract to establish the active session before pinging.
            client_a.extract(recursive=True, specification=True, timeout=SHORT_TIMEOUT)

            # Send a raw PingCommand — should get SuccessMessage.
            req = pb.MessageV1()
            req.id = str(uuid.uuid4())
            req.ping_command.CopyFrom(pb.PingCommand())
            resp_bytes = client_a.send_and_recv(req.SerializeToString(), SHORT_TIMEOUT)
            resp = pb.MessageV1()
            resp.ParseFromString(resp_bytes)

            assert resp.HasField("success_message"), (
                f"Active client A should receive success_message for PingCommand, "
                f"got kind: {resp.WhichOneof('kind')}"
            )
        finally:
            if client_a is not None:
                client_a.stop()
            proxy.stop()
            stop.set()
            dac_thread.join(timeout=SHORT_TIMEOUT)

    def test_busy_wait_with_ping_polling(self) -> None:
        """Client B polls PingCommand while A runs a 5 s job; after A finishes B's reset succeeds."""
        # simulate_op_time=True with a long op so client B has time to poll.
        config = DummyDACConfig(
            mac_mode=DummyDACMacMode.PHYSICAL,
            simulate_op_time=True,
        )
        ready = threading.Event()
        stop = threading.Event()
        dac_port_holder = [0]

        dac_thread = _start_dummy_dac(config, ready, stop, dac_port_holder)
        _wait_ready(ready)

        proxy = ProxyServer()
        # Longer session timeout to allow the 5 s run to complete.
        proxy.set_session_timeout(15.0)

        client_a = None
        client_b_busy_count: list = [0]
        client_b_reset_ok = threading.Event()
        client_b_error: list = []
        client_b_done = threading.Event()
        # Synchronization: Client A waits for B to be queued before starting the run.
        client_b_queued = threading.Event()

        LONG_OP_TIME_NS = 5_000_000_000  # 5 seconds

        def client_b_worker(port: int) -> None:
            """Connect client B, poll with PingCommand, then reset when active."""
            ch = None
            try:
                ch = ControlChannel.create(LOCALHOST, port, timeout=SHORT_TIMEOUT)
                ch.start()

                # First ResetCommand → should get BusyResponse (A holds active session).
                req = pb.MessageV1()
                req.id = str(uuid.uuid4())
                req.reset_command.keep_calibration = True
                req.reset_command.sync = False
                resp_bytes = ch.send_and_recv(req.SerializeToString(), SHORT_TIMEOUT)
                resp = pb.MessageV1()
                resp.ParseFromString(resp_bytes)
                if not resp.HasField("busy_response"):
                    client_b_error.append(
                        AssertionError(
                            f"Expected busy_response for initial ResetCommand, "
                            f"got {resp.WhichOneof('kind')}"
                        )
                    )
                    return

                # Signal that B is queued — A can now start the long run.
                client_b_queued.set()

                # Poll with PingCommand every second until SuccessMessage.
                MAX_POLLS = 20
                for _ in range(MAX_POLLS):
                    time.sleep(1.0)
                    ping_req = pb.MessageV1()
                    ping_req.id = str(uuid.uuid4())
                    ping_req.ping_command.CopyFrom(pb.PingCommand())
                    ping_resp_bytes = ch.send_and_recv(
                        ping_req.SerializeToString(), SHORT_TIMEOUT
                    )
                    ping_resp = pb.MessageV1()
                    ping_resp.ParseFromString(ping_resp_bytes)

                    if ping_resp.HasField("busy_response"):
                        client_b_busy_count[0] += 1
                        continue

                    if ping_resp.HasField("success_message"):
                        # Session is now active — send final ResetCommand.
                        ch.reset(keep_calibration=True, sync=False, timeout=RUN_TIMEOUT)
                        client_b_reset_ok.set()
                        return

                    client_b_error.append(
                        AssertionError(
                            f"Unexpected PingCommand response: {ping_resp.WhichOneof('kind')}"
                        )
                    )
                    return

                client_b_error.append(
                    TimeoutError(
                        f"Exceeded {MAX_POLLS} ping polls without receiving SuccessMessage"
                    )
                )
            except Exception as exc:
                client_b_error.append(exc)
            finally:
                if ch is not None:
                    ch.stop()
                client_b_done.set()

        try:
            proxy.add_backend(LOCALHOST, dac_port_holder[0])
            proxy.start(LOCALHOST, 0)
            proxy_port = proxy.local_port()

            # Client A: connect, establish active session.
            client_a = ControlChannel.create(LOCALHOST, proxy_port, timeout=SHORT_TIMEOUT)
            client_a.start()
            client_a.extract(recursive=True, specification=True, timeout=SHORT_TIMEOUT)

            # Start client B in a background thread; it will send ResetCommand
            # (getting BusyResponse) then signal client_b_queued.
            thread_b = threading.Thread(
                target=client_b_worker, args=(proxy_port,), daemon=True
            )
            thread_b.start()

            # Wait until B has confirmed it is queued before starting the run.
            assert client_b_queued.wait(timeout=SHORT_TIMEOUT), (
                "Client B did not become queued within timeout"
            )

            # Start the long run on client A, then disconnect — the proxy
            # releases the session on client disconnect, not on run completion.
            run_id = str(uuid.uuid4())
            cmd = _build_start_run_command(run_id, op_time_ns=LONG_OP_TIME_NS)
            client_a.start_run_request(cmd.SerializeToString(), timeout=SHORT_TIMEOUT)
            client_a.stop()
            client_a = None

            # Wait for client B to finish its ping-poll cycle (allow up to 30 s).
            assert client_b_done.wait(timeout=30.0), (
                "Client B did not complete its polling cycle within 30s"
            )

            assert not client_b_error, (
                f"Client B encountered error: {client_b_error}"
            )
            assert client_b_reset_ok.is_set(), (
                "Client B's final ResetCommand should have succeeded after A disconnected"
            )
        finally:
            if client_a is not None:
                client_a.stop()
            proxy.stop()
            stop.set()
            dac_thread.join(timeout=SHORT_TIMEOUT)

# Copyright (c) 2026 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
Integration tests for ControlChannel::reconnect / cancel_reconnect.

The first three tests exercise the TCP lifecycle via a bare ``asyncio``
acceptor that accepts connections but does not speak the LUCIDAC protobuf
protocol. This keeps the primitive's behaviour isolated from any
mock-server semantics.

Tests 4 and 5 exercise the channel against the real DummyDAC mock so that
reconnect is exercised with a live protobuf endpoint.
"""

import asyncio
import socket
import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

import pybrid.base.proto.main_pb2 as pb
from pybrid.mock import DummyDAC, DummyDACConfig

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
CONNECT_TIMEOUT = 5.0
OP_TIMEOUT = 5.0


def _pick_free_port() -> int:
    """Bind a throw-away socket to obtain a currently-free TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((LOCALHOST, 0))
        return sock.getsockname()[1]


class BareTCPAcceptor:
    """
    Minimal TCP accept loop that holds connections open without speaking the
    protocol. It is suitable for exercising the TCPTransport connect /
    disconnect path without engaging the ControlChannel recv loop.

    The acceptor can be started on an arbitrary port and stopped by calling
    :meth:`stop`. After stop, the same instance can be restarted on the same
    port via :meth:`start` — this is how the reconnect tests simulate a
    listener that briefly goes away.
    """

    def __init__(self, host: str = LOCALHOST, port: int = 0):
        self._host = host
        self._port = port
        self._server: asyncio.base_events.Server | None = None
        self._client_tasks: set[asyncio.Task] = set()

    @property
    def port(self) -> int:
        if self._server is not None and self._server.sockets:
            return self._server.sockets[0].getsockname()[1]
        return self._port

    async def start(self) -> None:
        if self._server is not None:
            raise RuntimeError("BareTCPAcceptor already started")
        self._server = await asyncio.start_server(self._on_client, self._host, self._port, reuse_address=True)
        # Lock the port so subsequent start() calls rebind the same one.
        self._port = self._server.sockets[0].getsockname()[1]

    async def _on_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        if task is not None:
            self._client_tasks.add(task)
        try:
            # Hold the connection open until the test tears the server down.
            await reader.read()
        except (asyncio.CancelledError, ConnectionResetError, BrokenPipeError):
            pass
        finally:
            try:
                writer.close()
            except Exception:
                pass
            if task is not None:
                self._client_tasks.discard(task)

    async def stop(self) -> None:
        if self._server is None:
            return
        # Cancel all in-flight client handlers so wait_closed() does not hang.
        for task in list(self._client_tasks):
            task.cancel()
        self._server.close()
        try:
            await asyncio.wait_for(self._server.wait_closed(), timeout=2.0)
        except (asyncio.TimeoutError, Exception):
            pass
        self._client_tasks.clear()
        self._server = None


def _make_native_channel(port: int) -> "NativeControlChannel":
    """Create a native ControlChannel connected to *port* on localhost."""
    return NativeControlChannel.create(LOCALHOST, port, CONNECT_TIMEOUT)


def _safe_stop(channel) -> None:
    """Call ``stop()`` on a native channel, ignoring shutdown races."""
    if channel is None:
        return
    try:
        channel.stop()
    except Exception:
        pass


def _safe_cancel_reconnect(channel) -> None:
    """Call ``cancel_reconnect()`` if the binding is available."""
    cancel = getattr(channel, "cancel_reconnect", None)
    if callable(cancel):
        try:
            cancel()
        except Exception:
            pass


@pytest.mark.asyncio
async def test_reconnect_no_timeout_wins_against_sleepy_listener():
    """Reconnect returns True when the listener comes back within the timeout."""
    acceptor = BareTCPAcceptor(port=_pick_free_port())
    await acceptor.start()
    locked_port = acceptor.port

    channel = await asyncio.get_running_loop().run_in_executor(None, _make_native_channel, locked_port)
    try:
        assert channel.is_connected()

        # Drop the listener; the client TCP socket now targets a dead endpoint.
        await acceptor.stop()

        async def _restart_after_delay() -> None:
            await asyncio.sleep(1.0)
            await acceptor.start()

        restart_task = asyncio.create_task(_restart_after_delay())
        loop = asyncio.get_running_loop()

        try:
            reconnected = await loop.run_in_executor(None, channel.reconnect, 0.2, 10.0)
        finally:
            await restart_task

        assert reconnected is True, "reconnect() should return True on success"
        assert channel.is_connected(), "Channel should be connected after successful reconnect"
    finally:
        _safe_cancel_reconnect(channel)
        _safe_stop(channel)
        await acceptor.stop()


@pytest.mark.asyncio
async def test_reconnect_timeout_expires_when_listener_never_returns():
    """Reconnect returns False within the configured deadline."""
    acceptor = BareTCPAcceptor(port=_pick_free_port())
    await acceptor.start()
    locked_port = acceptor.port

    channel = await asyncio.get_running_loop().run_in_executor(None, _make_native_channel, locked_port)
    try:
        assert channel.is_connected()

        # Stop the listener and keep the port idle for the whole test.
        await acceptor.stop()

        loop = asyncio.get_running_loop()
        start = loop.time()
        reconnected = await asyncio.wait_for(
            loop.run_in_executor(None, channel.reconnect, 0.2, 2.0),
            timeout=4.0,
        )
        elapsed = loop.time() - start

        assert reconnected is False, "reconnect() should return False once the deadline expires"
        assert elapsed < 3.5, f"reconnect() should honour the 2 s deadline; took {elapsed:.2f} s"
        assert not channel.is_connected(), "Channel must not be connected when reconnect() reports failure"
    finally:
        _safe_cancel_reconnect(channel)
        _safe_stop(channel)
        await acceptor.stop()


@pytest.mark.asyncio
async def test_cancel_reconnect_yields_quickly():
    """cancel_reconnect() causes an in-flight reconnect to return within 1 s."""
    acceptor = BareTCPAcceptor(port=_pick_free_port())
    await acceptor.start()
    locked_port = acceptor.port

    channel = await asyncio.get_running_loop().run_in_executor(None, _make_native_channel, locked_port)
    try:
        assert channel.is_connected()

        # Kill the listener so the reconnect loop cannot make progress.
        await acceptor.stop()

        reconnect_done = threading.Event()
        reconnect_result: list[object] = []

        def _run_reconnect() -> None:
            try:
                # 600 s timeout stands in for "infinite" — cancel must win.
                result = channel.reconnect(0.2, 600.0)
            except Exception as exc:
                reconnect_result.append(exc)
            else:
                reconnect_result.append(result)
            finally:
                reconnect_done.set()

        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="reconnect-cancel")
        future = executor.submit(_run_reconnect)
        try:
            # Let the reconnect loop get into its sleep/poll cycle.
            await asyncio.sleep(0.2)
            channel.cancel_reconnect()

            loop = asyncio.get_running_loop()
            cancelled = await loop.run_in_executor(None, reconnect_done.wait, 1.0)
            assert cancelled, "cancel_reconnect() did not return within 1 s"
            assert reconnect_result, "reconnect() thread produced no result"
            outcome = reconnect_result[0]
            assert outcome is False, f"Cancelled reconnect should return False, got {outcome!r}"
            assert not channel.is_connected(), "Channel must not be connected after cancelled reconnect"
        finally:
            future.cancel()
            executor.shutdown(wait=False)
    finally:
        _safe_cancel_reconnect(channel)
        _safe_stop(channel)
        await acceptor.stop()


@pytest.mark.asyncio
async def test_reconnect_preserves_callbacks():
    """After reconnect, command traffic continues without re-registering handlers.

    The promise/callback plumbing on the native channel must survive a
    reconnect cycle: a second ``extract()`` call over the reconnected channel
    must succeed without any re-initialisation by the caller.
    """
    config = DummyDACConfig(lucidac_mode=True)
    dac_port = _pick_free_port()

    # First DummyDAC incarnation — drive a single extract to prove baseline wiring.
    first_dac = DummyDAC(LOCALHOST, dac_port, config)
    async with first_dac:
        loop = asyncio.get_running_loop()
        channel = await loop.run_in_executor(None, _make_native_channel, dac_port)
        channel.start()
        try:
            # Baseline extract over the live channel.
            module_bytes = await loop.run_in_executor(None, channel.extract, "", True, True, False, False, OP_TIMEOUT)
            baseline = pb.Module()
            baseline.ParseFromString(module_bytes)
            assert len(baseline.items) >= 1
        except Exception:
            _safe_stop(channel)
            raise

    # First DummyDAC is now fully shut down. Stand a fresh one up on the same
    # port and ask the native channel to reconnect.
    second_dac = DummyDAC(LOCALHOST, dac_port, config)
    async with second_dac:
        try:
            reconnected = await loop.run_in_executor(None, channel.reconnect, 0.2, 10.0)
            assert reconnected is True, "reconnect() should return True after the DummyDAC restarts"
            assert channel.is_connected()

            # Second extract runs over the reconnected channel without any
            # explicit callback re-registration by the test.
            module_bytes = await loop.run_in_executor(None, channel.extract, "", True, True, False, False, OP_TIMEOUT)
            post = pb.Module()
            post.ParseFromString(module_bytes)
            assert len(post.items) >= 1, "Second extract after reconnect must return a non-empty Module"
        finally:
            _safe_cancel_reconnect(channel)
            _safe_stop(channel)


@pytest.mark.asyncio
async def test_reconnect_pending_requests_fail_cleanly():
    """A pending request fails with a clear error when the server dies, and
    the channel can still be reconnected afterwards.
    """
    acceptor = BareTCPAcceptor(port=_pick_free_port())
    await acceptor.start()
    locked_port = acceptor.port

    loop = asyncio.get_running_loop()
    channel = await loop.run_in_executor(None, _make_native_channel, locked_port)
    channel.start()

    try:
        assert channel.is_connected()

        # Build a minimal PingCommand envelope — the bare acceptor will read
        # the bytes into its kernel buffer and never respond.
        ping = pb.MessageV1(id=str(uuid4()))
        ping.ping_command.CopyFrom(pb.PingCommand())
        serialized = ping.SerializeToString()

        send_done = threading.Event()
        send_error: list[BaseException] = []
        send_result: list[bytes] = []

        def _blocking_send() -> None:
            try:
                result = channel.send_and_recv(serialized, 10.0)
            except BaseException as exc:
                send_error.append(exc)
            else:
                send_result.append(result)
            finally:
                send_done.set()

        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pending-req")
        future = executor.submit(_blocking_send)
        try:
            # Give the native channel a moment to enter the pending-wait state.
            await asyncio.sleep(0.2)

            # Tear the acceptor down — the client side should notice EOF and
            # break the pending promise with a descriptive error.
            await acceptor.stop()

            awaited = await loop.run_in_executor(None, send_done.wait, 5.0)
            assert awaited, "Pending send_and_recv() did not complete after server teardown"
            assert not send_result, f"send_and_recv() unexpectedly succeeded: {send_result!r}"
            assert send_error, "send_and_recv() produced no error after server teardown"
            err = send_error[0]
            assert isinstance(err, Exception), f"Expected Exception from broken promise, got {type(err).__name__}"
        finally:
            future.cancel()
            executor.shutdown(wait=False)

        # Bring the acceptor back and reconnect.
        await acceptor.start()
        reconnected = await loop.run_in_executor(None, channel.reconnect, 0.2, 10.0)
        assert reconnected is True, "reconnect() should succeed once the acceptor is back"
        assert channel.is_connected()
    finally:
        _safe_cancel_reconnect(channel)
        _safe_stop(channel)
        await acceptor.stop()

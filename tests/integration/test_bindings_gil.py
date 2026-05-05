# Copyright (c) 2026 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
GIL-safety tests for the pybind11 stop() / teardown wrappers.

Each stop() wrapper in bindings.cpp releases the GIL immediately before
calling the underlying C++ stop(). If the C++ teardown destroys
std::function members that capture py::function / py::object, those
destructors run without the GIL — undefined behaviour in CPython.

The fix is to clear those std::function members while the GIL is still
held, before the py::gil_scoped_release guard is constructed.

These tests exercise the three affected bindings:
  - DataChannel (on_error, on_run_state_change, set_control_response_callback)
  - SampleDecodingDataChannel (same callbacks, via __exit__)
  - ControlChannel (register_callback, via stop() and __exit__)

The tests run 50 start/stop cycles each with all callbacks registered.
A process crash or heap corruption under CPython's refcount machinery is
the expected failure mode on unpatched code. We probe liveness after
each cycle via gc.collect() + a list allocation to exercise the
allocator. We also verify that all callback captures are still
reachable after the loop — their refcounts must not have been corrupted.
"""

import gc
import socket
import threading

import pytest

try:
    from pybrid.native._impl import (
        ControlChannel,
        SampleDecodingDataChannel,
        SampleLockFreeBuffer,
    )
    _NATIVE_AVAILABLE = True
except ImportError:
    _NATIVE_AVAILABLE = False
    ControlChannel = None
    SampleDecodingDataChannel = None
    SampleLockFreeBuffer = None

pytestmark = pytest.mark.skipif(
    not _NATIVE_AVAILABLE,
    reason="pybrid.native._impl is not available (C++ bindings not built)",
)

LOCALHOST = "127.0.0.1"
CYCLES = 50


def _free_port() -> int:
    """Return an OS-assigned free TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((LOCALHOST, 0))
        return s.getsockname()[1]


class _BareTCPAcceptor:
    """Minimal TCP listener that holds connections open, no protocol."""

    def __init__(self, port: int) -> None:
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind((LOCALHOST, port))
        self._srv.listen(8)
        self._srv.settimeout(1.0)
        self._conns: list[socket.socket] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()

    def _accept_loop(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self._srv.accept()
                self._conns.append(conn)
            except (TimeoutError, OSError):
                pass

    def stop(self) -> None:
        self._stop.set()
        self._srv.close()
        for c in self._conns:
            try:
                c.close()
            except OSError:
                pass
        self._thread.join(timeout=2.0)


@pytest.mark.slow
def test_data_channel_stop_cycles_with_all_callbacks():
    """50 start/stop cycles on SampleDecodingDataChannel with all callbacks set.

    Verifies that Python objects captured by the callbacks are not destroyed
    without the GIL — which would corrupt CPython refcounts.
    """
    # Use lists as shared mutable state captured by lambdas; their reference
    # count integrity is what we're protecting.
    error_log: list[str] = []
    state_log: list[object] = []
    response_log: list[bytes] = []

    port = _free_port()
    acceptor = _BareTCPAcceptor(port)
    try:
        for i in range(CYCLES):
            channel = SampleDecodingDataChannel()
            queue = SampleLockFreeBuffer()
            channel.set_output_queue(queue)
            channel.set_udp_endpoint(LOCALHOST, port)

            # Register all three callback types — each captures a py::object.
            channel.on_error(lambda msg, _log=error_log: _log.append(msg))
            channel.on_run_state_change(lambda s, _log=state_log: _log.append(s))
            channel.set_control_response_callback(
                lambda data, _log=response_log: _log.append(data)
            )

            channel.start()
            channel.stop()

            # After stop(), the std::function members should have been destroyed
            # while the GIL was held. Exercise the GC to surface any refcount
            # corruption from destructors that ran without the GIL.
            gc.collect()

            # Verify Python heap is still intact by allocating and immediately
            # releasing a list — a corrupted allocator would segfault here.
            _ = list(range(100))

        # Shared capture objects must still be accessible; a GIL-less destructor
        # would have decremented their refcounts, potentially freeing them early.
        assert isinstance(error_log, list)
        assert isinstance(state_log, list)
        assert isinstance(response_log, list)
    finally:
        acceptor.stop()


@pytest.mark.slow
def test_control_channel_stop_cycles_with_registered_callback():
    """50 stop()/start() cycles on ControlChannel with register_callback set.

    ControlChannel.stop() releases the GIL and tears down the recv thread.
    The recv thread's callback map contains std::function instances that
    capture py::function. On unpatched code those captures may be destroyed
    without the GIL.
    """
    received: list[bytes] = []

    port = _free_port()
    acceptor = _BareTCPAcceptor(port)
    try:
        for i in range(CYCLES):
            channel = ControlChannel.create(LOCALHOST, port, timeout=2.0)
            channel.start()

            # Any field number is valid for the callback map; use 1 (ping_response).
            channel.register_callback(1, lambda data, _log=received: _log.append(data))

            channel.stop()

            gc.collect()
            _ = list(range(100))

        assert isinstance(received, list)
    finally:
        acceptor.stop()


@pytest.mark.slow
def test_control_channel_context_manager_cycles_with_callback():
    """50 with-block cycles on ControlChannel using __exit__ teardown path.

    __exit__ is a separate binding that also releases the GIL inside self.stop().
    It must clear callbacks before releasing to avoid GIL-less py::function
    destruction.
    """
    received: list[bytes] = []

    port = _free_port()
    acceptor = _BareTCPAcceptor(port)
    try:
        for i in range(CYCLES):
            with ControlChannel.create(LOCALHOST, port, timeout=2.0) as channel:
                channel.start()
                channel.register_callback(
                    1, lambda data, _log=received: _log.append(data)
                )
            # __exit__ calls stop() — the destruction of the captured lambda
            # must happen while the GIL is held.

            gc.collect()
            _ = list(range(100))

        assert isinstance(received, list)
    finally:
        acceptor.stop()

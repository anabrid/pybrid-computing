# Copyright (c) 2026 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import asyncio
import gc
import os
import threading

import psutil
import pytest

try:
    from pybrid.native._impl import ControlChannel, ProxyServer, _client_session_alive_count

    _NATIVE_AVAILABLE = True
except ImportError:
    _NATIVE_AVAILABLE = False
    ControlChannel = None
    ProxyServer = None
    _client_session_alive_count = None

from pybrid.mock import DummyDAC, DummyDACConfig, DummyDACMacMode

pytestmark = pytest.mark.skipif(
    not _NATIVE_AVAILABLE,
    reason="pybrid.native._impl is not available (C++ bindings not built)",
)

LOCALHOST = "127.0.0.1"
CONNECT_TIMEOUT = 5.0  # seconds per ControlChannel.create() call
WARMUP_ROUNDS = 10  # first-touch allocations settle
MAIN_ROUNDS = 200  # iterations for the growth measurement

# A 50 MiB absolute cap: the pre-fix leak grew by hundreds of MiB over 200
# connections; this bound is generous enough to tolerate normal allocator
# noise while still catching any monotonic retention chain.
RSS_BOUND_BYTES = 50 * 1024 * 1024


def _start_dummy_dac(
    config: DummyDACConfig,
    ready_event: threading.Event,
    stop_event: threading.Event,
    port_holder: list,
) -> threading.Thread:
    """Launch DummyDAC in a background daemon thread on an OS-assigned port."""

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


def _wait_ready(event: threading.Event, timeout: float = CONNECT_TIMEOUT) -> None:
    """Raise RuntimeError if the ready event is not set within *timeout* seconds."""
    if not event.wait(timeout=timeout):
        raise RuntimeError(f"DummyDAC did not become ready within {timeout}s")


def _one_connect_disconnect(proxy_port: int) -> None:
    """Open one ControlChannel to the proxy and immediately stop it."""
    channel = ControlChannel.create(LOCALHOST, proxy_port, timeout=CONNECT_TIMEOUT)
    channel.start()
    channel.stop()


@pytest.mark.slow
def test_proxy_rss_bounded_under_reconnects():
    """RSS growth stays below 50 MiB across 200 connect/disconnect cycles.

    Spins up an in-process DummyDAC and ProxyServer, then opens and closes
    200 client ControlChannels in sequence. RSS is sampled after 10 warm-up
    rounds (so first-touch allocations are already accounted for) and again
    after the 200th round. The delta must stay below RSS_BOUND_BYTES.
    """
    config = DummyDACConfig(mac_mode=DummyDACMacMode.PHYSICAL)
    ready = threading.Event()
    stop = threading.Event()
    dac_port_holder = [0]

    dac_thread = _start_dummy_dac(config, ready, stop, dac_port_holder)
    _wait_ready(ready)

    proxy = ProxyServer()
    # Generous session timeout so the proxy processes each disconnect cleanly
    # before the next connect arrives.
    proxy.set_session_timeout(2.0)

    process = psutil.Process(os.getpid())
    baseline = 0
    final = 0

    try:
        proxy.add_backend(LOCALHOST, dac_port_holder[0])
        proxy.start(LOCALHOST, 0)
        proxy_port = proxy.local_port()

        # Warm-up: settle first-touch allocations (OS page faults, internal
        # C++ container growth to steady state, Python import caches).
        for _ in range(WARMUP_ROUNDS):
            _one_connect_disconnect(proxy_port)
            gc.collect()

        baseline = process.memory_info().rss

        # Main measurement loop.
        for _ in range(MAIN_ROUNDS):
            _one_connect_disconnect(proxy_port)
            gc.collect()

        gc.collect()
        assert (
            _client_session_alive_count() == 0
        ), f"ClientSession leak: {_client_session_alive_count()} sessions still alive after reconnect loop"

        final = process.memory_info().rss

    finally:
        proxy.stop()
        stop.set()
        dac_thread.join(timeout=CONNECT_TIMEOUT)

    delta_bytes = final - baseline
    delta_mib = delta_bytes / (1024 * 1024)
    assert delta_bytes < RSS_BOUND_BYTES, (
        f"RSS grew by {delta_mib:.1f} MiB over {MAIN_ROUNDS} connect/disconnect "
        f"cycles (baseline {baseline // 1024} KiB → final {final // 1024} KiB). "
        f"Bound is {RSS_BOUND_BYTES // (1024 * 1024)} MiB. "
        "This indicates a memory retention chain in the proxy session lifecycle."
    )

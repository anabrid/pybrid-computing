# Copyright (c) 2022-2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""Tests for the DummyDAC server skeleton."""

import asyncio
import re

import pytest

from pybrid.mock import DummyDAC, DummyDACConfig, DummyDACMacMode
from pybrid.redac.run import RunError


def _suppress_run_error_handler(loop, context):
    """
    Custom exception handler that suppresses RunError from unhandled futures.

    These errors are expected when connections close without proper protocol
    communication and should not be logged.
    """
    exception = context.get("exception")
    if exception is not None and isinstance(exception, RunError):
        return
    loop.default_exception_handler(context)


@pytest.mark.asyncio
async def test_server_starts_and_stops():
    """Verify server starts and stops cleanly."""
    config = DummyDACConfig()
    async with DummyDAC("127.0.0.1", 15732, config) as server:
        assert server._server is not None
        assert server._server.is_serving()


@pytest.mark.asyncio
async def test_server_accepts_tcp_connection():
    """Verify server accepts raw TCP connections."""
    # Suppress RunError from protocol handler when connection closes
    # without proper protocol communication
    loop = asyncio.get_running_loop()
    old_handler = loop.get_exception_handler()
    loop.set_exception_handler(_suppress_run_error_handler)

    try:
        config = DummyDACConfig()
        async with DummyDAC("127.0.0.1", 15733, config):
            reader, writer = await asyncio.open_connection("127.0.0.1", 15733)
            assert reader is not None
            writer.close()
            await writer.wait_closed()
    finally:
        loop.set_exception_handler(old_handler)


@pytest.mark.asyncio
async def test_virtual_mac_generation():
    """Verify virtual MAC addresses are generated correctly."""
    config = DummyDACConfig(mac_mode=DummyDACMacMode.VIRTUAL)
    async with DummyDAC("127.0.0.1", 15734, config) as server:
        assert server._carrier_macs == ["00-00-00-00-00-00", "00-00-00-00-00-01"]


@pytest.mark.asyncio
async def test_physical_mac_generation():
    """Verify physical MAC addresses are hardcoded and valid format."""
    config = DummyDACConfig(mac_mode=DummyDACMacMode.PHYSICAL)
    async with DummyDAC("127.0.0.1", 15735, config) as server:
        assert len(server._carrier_macs) == 2
        mac_pattern = re.compile(r"^([0-9A-F]{2}-){5}[0-9A-F]{2}$")
        for mac in server._carrier_macs:
            assert mac_pattern.match(mac), f"Invalid MAC format: {mac}"
        # Physical MACs should be the hardcoded realistic ones
        assert server._carrier_macs == ["AB-CD-EF-12-34-56", "AB-CD-EF-12-34-57"]

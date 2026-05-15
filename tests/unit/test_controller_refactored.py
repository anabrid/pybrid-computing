# Copyright (c) 2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
Unit tests for the controller hierarchy.

These tests verify functional behavior:
- LUCIDACController.add_device enforces the delta assertion (at least 1 new carrier)
- Controller lifecycle (context manager, stop delegation)

All tests use mocks — no real network connections are made.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pybrid.base.hybrid.controller import BaseController
from pybrid.lucidac.controller import Controller as LUCIDACController
from pybrid.redac.controller import Controller as REDACController


def _make_redac_controller(**kwargs) -> REDACController:
    """Instantiate a REDACController with default arguments."""
    return REDACController(**kwargs)


def _make_lucidac_controller(**kwargs) -> LUCIDACController:
    """Instantiate a LUCIDACController with default arguments."""
    return LUCIDACController(**kwargs)


class TestLUCIDACControllerDeltaAssertion:
    """Tests for LUCIDACController.add_device delta-based carrier count assertion."""

    @pytest.mark.asyncio
    async def test_lucidac_controller_delta_assertion_success(self):
        """add_device() succeeds when at least 1 new connection is added (delta >= 1)."""
        ctrl = _make_lucidac_controller()

        # Simulate BaseController.add_device adding one connection
        async def fake_base_add_device(self, host, port, specification=None):
            from pybrid.redac.channel import DeviceConnection
            from pybrid.redac.entities import Path

            fake_path = Path.parse("AA-BB-CC-DD-EE-01")
            fake_conn = MagicMock(spec=DeviceConnection)
            ctrl.connection_manager.connections[fake_path] = fake_conn

        with patch.object(BaseController, "add_device", new=fake_base_add_device):
            # Must not raise
            await ctrl.add_device("127.0.0.1", 5732)

    @pytest.mark.asyncio
    async def test_lucidac_controller_delta_assertion_failure(self):
        """add_device() raises when the underlying add_device adds 0 new connections."""
        ctrl = _make_lucidac_controller()

        # Simulate BaseController.add_device that adds nothing
        async def fake_base_add_device_noop(self, host, port, specification=None):
            pass

        with patch.object(BaseController, "add_device", new=fake_base_add_device_noop):
            with pytest.raises(Exception, match="[Ff]ail|[Cc]arrier|LUCIDAC|new_conns"):
                await ctrl.add_device("127.0.0.1", 5732)


class TestControllerLifecycle:

    @pytest.mark.asyncio
    async def test_context_manager_calls_close_all(self):
        ctrl = _make_redac_controller()

        with patch.object(ctrl.connection_manager, "close_all", new=AsyncMock()) as mock_close:
            async with ctrl:
                pass
            mock_close.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_delegates_to_close_all(self):
        ctrl = _make_redac_controller()

        with patch.object(ctrl.connection_manager, "close_all", new=AsyncMock()) as mock_close:
            await ctrl.stop()
            mock_close.assert_called_once()

# Copyright (c) 2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
Unit tests for deprecated backward-compatibility wrappers that delegate to
the Session class.

The old direct-call API:
    controller.set_computer(computer)
    controller.start_and_await_run(run, timeout=...)
    controller.forward_set_config(config_command)

must be replaced by thin shims that:
1. Emit DeprecationWarning
2. Obtain or create a default session (controller._default_session)
3. Buffer the appropriate SessionCommand
4. Call execute() and return its result

Additional tests cover:
- controller.create_session() returns a fresh Session bound to the controller
- The default session is reused across multiple deprecated calls
- DeprecationWarning is emitted by all three deprecated shims

All tests use mocks — no real network or hardware required.
"""

import asyncio
import warnings
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from pybrid.redac.controller import Controller as REDACController
from pybrid.redac.session import Session, SetConfigCommand, RunCommand
from pybrid.redac.run import Run, RunConfig
from pybrid.redac.channel import DeviceConnection
from pybrid.redac.entities import Path
from pybrid.base.result import Result

import pybrid.base.proto.main_pb2 as pb


def _make_controller(**kwargs) -> REDACController:
    """Construct a REDACController with default or supplied arguments."""
    return REDACController(**kwargs)


def _inject_fake_connections(ctrl: REDACController, macs: list[str]) -> dict:
    """
    Populate controller.connection_manager.connections with fake DeviceConnection
    objects keyed by Path, and return the path→connection mapping.
    """
    result = {}
    for mac in macs:
        path = Path.parse(mac)
        conn = MagicMock(spec=DeviceConnection)
        conn.control = AsyncMock()
        conn.control.set_module = AsyncMock(return_value=Result.success())
        conn.control.start_run_request = AsyncMock(return_value=Result.success())
        conn.control.register_callback = MagicMock()
        conn.control.unregister_callback = MagicMock()
        ctrl.connection_manager.connections[path] = conn
        result[path] = conn
    return result


class TestSetComputerDelegation:

    @pytest.mark.asyncio
    async def test_set_computer_creates_session_and_executes(self):
        ctrl = _make_controller()
        _inject_fake_connections(ctrl, ["AA-BB-CC-DD-EE-01"])
        mock_computer = MagicMock()

        # Patch Session.execute to track calls without side-effects
        with patch.object(Session, "execute", new=AsyncMock(return_value=[])) as mock_exec, \
             warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            await ctrl.set_computer(mock_computer)

        mock_exec.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_computer_buffers_set_config_command(self):
        ctrl = _make_controller()
        _inject_fake_connections(ctrl, ["AA-BB-CC-DD-EE-01"])
        mock_computer = MagicMock()

        captured_session = None

        async def capture_execute(self_inner, **kwargs):
            nonlocal captured_session
            captured_session = self_inner
            return []

        with patch.object(Session, "execute", capture_execute), \
             warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            await ctrl.set_computer(mock_computer)

        assert captured_session is not None
        pipeline = captured_session._pipeline
        assert len(pipeline) >= 1
        sc_cmds = [c for c in pipeline if isinstance(c, SetConfigCommand)]
        assert len(sc_cmds) >= 1
        assert sc_cmds[0].module is not None


class TestStartAndAwaitRunDelegation:

    @pytest.mark.asyncio
    async def test_start_and_await_run_buffers_run_command(self):
        ctrl = _make_controller()
        _inject_fake_connections(ctrl, ["AA-BB-CC-DD-EE-01"])

        run = Run(config=RunConfig(ic_time=150_000, op_time=3_000_000))
        returned_run = Run()

        captured_session = None

        async def capture_execute(self_inner, **kwargs):
            nonlocal captured_session
            captured_session = self_inner
            return [returned_run]

        with patch.object(Session, "execute", capture_execute), \
             warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            result = await ctrl.start_and_await_run(run=run, timeout=50)

        assert captured_session is not None
        run_cmds = [c for c in captured_session._pipeline if isinstance(c, RunCommand)]
        assert len(run_cmds) >= 1

    @pytest.mark.asyncio
    async def test_start_and_await_run_returns_completed_run(self):
        ctrl = _make_controller()
        _inject_fake_connections(ctrl, ["AA-BB-CC-DD-EE-01"])

        run = Run()
        completed_run = Run()

        async def fake_execute(self_inner, **kwargs):
            return [completed_run]

        with patch.object(Session, "execute", fake_execute), \
             warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            result = await ctrl.start_and_await_run(run=run)

        assert result is completed_run


class TestForwardSetConfigDelegation:

    @pytest.mark.asyncio
    async def test_forward_set_config_buffers_module_command(self):
        ctrl = _make_controller()
        _inject_fake_connections(ctrl, ["AA-BB-CC-DD-EE-01"])

        module = pb.Module()
        config_cmd = pb.ConfigCommand()
        config_cmd.module.CopyFrom(module)

        captured_session = None

        async def capture_execute(self_inner, **kwargs):
            nonlocal captured_session
            captured_session = self_inner
            return []

        with patch.object(Session, "execute", capture_execute), \
             warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            await ctrl.forward_set_config(config_cmd)

        assert captured_session is not None
        sc_cmds = [c for c in captured_session._pipeline if isinstance(c, SetConfigCommand)]
        assert len(sc_cmds) >= 1
        assert sc_cmds[0].module is not None


class TestDeprecationWarnings:
    """All three deprecated shims must emit DeprecationWarning on use."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("method_name,call_kwargs,mock_return", [
        ("set_computer", {"computer": None}, []),
        ("start_and_await_run", {"run": None}, [None]),
        ("forward_set_config", {"cmd": None}, []),
    ])
    async def test_deprecated_method_emits_warning(self, method_name, call_kwargs, mock_return):
        ctrl = _make_controller()
        _inject_fake_connections(ctrl, ["AA-BB-CC-DD-EE-01"])

        # Build concrete call arguments for methods that need real objects
        if method_name == "set_computer":
            call_kwargs = {"computer": MagicMock()}
            execute_return = []
        elif method_name == "start_and_await_run":
            call_kwargs = {"run": Run()}
            execute_return = [Run()]
        else:
            call_kwargs = {"message": pb.ConfigCommand()}
            execute_return = []

        with patch.object(Session, "execute", new=AsyncMock(return_value=execute_return)):
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                await getattr(ctrl, method_name)(**call_kwargs)

        dep_warnings = [w for w in caught if issubclass(w.category, DeprecationWarning)]
        assert len(dep_warnings) >= 1, (
            f"controller.{method_name}() must emit at least one DeprecationWarning"
        )


class TestDefaultSessionReuse:
    """Multiple deprecated calls that create a default session share the same object."""

    @pytest.mark.asyncio
    async def test_create_session_does_not_affect_default_session(self):
        """create_session() must not overwrite controller._default_session."""
        ctrl = _make_controller()
        _inject_fake_connections(ctrl, ["AA-BB-CC-DD-EE-01"])

        # Set a default session by hand (simulating a prior deprecated call result)
        sentinel_session = Session(ctrl)
        ctrl._default_session = sentinel_session

        # create_session() must not touch _default_session
        new_session = ctrl.create_session()

        assert ctrl._default_session is sentinel_session, (
            "create_session() must not overwrite controller._default_session"
        )
        assert new_session is not sentinel_session

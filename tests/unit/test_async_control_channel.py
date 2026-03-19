# Copyright (c) 2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""Tests for the AsyncControlChannel async wrapper."""

import asyncio
import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from pybrid.redac.control import AsyncControlChannel
from pybrid.base.result import Result

# We mock the native module since it may not be built
import pybrid.base.proto.main_pb2 as pb


class TestAsyncControlChannelUnit:

    def _make_mock_native(self):
        """Create a mock NativeControlChannel."""
        native = MagicMock()
        native.remote_host.return_value = "127.0.0.1"
        native.remote_port.return_value = 5732
        native.is_connected.return_value = True
        native.is_running.return_value = False
        return native

    async def test_send(self):
        """send() serializes and delegates."""
        native = self._make_mock_native()
        channel = AsyncControlChannel(native)
        msg = pb.MessageV1()
        msg.id = "test-uuid"
        msg.extract_command.CopyFrom(pb.ExtractCommand(recursive=True, specification=True))
        await channel.send(msg)
        native.send.assert_called_once()
        # Verify the arg is bytes
        call_args = native.send.call_args
        assert isinstance(call_args[0][0], bytes)

    async def test_send_and_recv(self):
        """send_and_recv() round-trips serialization."""
        native = self._make_mock_native()
        # Build a response with an extract_response containing a Module with one item
        response = pb.MessageV1()
        response.id = "test-uuid"
        item = pb.Item()
        item.entity.path = "/test"
        item.entity_specification.entity.id = "/test"
        response.extract_response.module.items.append(item)
        native.send_and_recv.return_value = response.SerializeToString()

        channel = AsyncControlChannel(native)
        msg = pb.MessageV1()
        msg.id = "test-uuid"
        msg.extract_command.CopyFrom(pb.ExtractCommand(recursive=True, specification=True))

        result = await channel.send_and_recv(msg)
        assert result.id == "test-uuid"
        assert result.extract_response.module.items[0].entity_specification.entity.id == "/test"

    async def test_extract(self):
        """extract() delegates to native.extract() with correct arguments and deserializes the result."""
        native = self._make_mock_native()

        module = pb.Module()
        item = pb.Item()
        item.entity.path = "/test-entity"
        item.entity_specification.entity.id = "/test-entity"
        module.items.append(item)
        native.extract.return_value = module.SerializeToString()

        channel = AsyncControlChannel(native)
        result = await channel.extract(specification=True, recursive=True)

        assert isinstance(result, pb.Module)
        assert result.items[0].entity_specification.entity.id == "/test-entity"
        native.extract.assert_called_once_with("", True, True, False, False, 5.0)

    async def test_extract_with_path_and_configuration(self):
        """extract() passes path and configuration flag through to native.extract()."""
        native = self._make_mock_native()
        native.extract.return_value = pb.Module().SerializeToString()

        channel = AsyncControlChannel(native)
        result = await channel.extract("/", configuration=True, recursive=True)

        assert isinstance(result, pb.Module)
        native.extract.assert_called_once_with("/", True, False, True, False, 5.0)

    async def test_set_module(self):
        """set_module() delegates to native.set_module() and returns Result on success."""
        native = self._make_mock_native()
        native.set_module.return_value = True

        channel = AsyncControlChannel(native)
        module = pb.Module()
        result = await channel.set_module(module)

        assert result.ok
        native.set_module.assert_called_once()
        sent_bytes = native.set_module.call_args[0][0]
        assert sent_bytes == module.SerializeToString()

    async def test_reset(self):
        """reset() delegates to native.reset() with correct parameters."""
        native = self._make_mock_native()

        channel = AsyncControlChannel(native)
        await channel.reset(keep_calibration=False, sync=True)

        native.reset.assert_called_once_with(False, True, 5.0)

    async def test_authenticate(self):
        """authenticate() delegates to native.authenticate() and returns Result on success."""
        native = self._make_mock_native()
        native.authenticate.return_value = True

        channel = AsyncControlChannel(native)
        result = await channel.authenticate("my-token")

        assert result.ok
        native.authenticate.assert_called_once_with("my-token", 5.0)

    def test_register_callback(self):
        """register_callback() wraps the callback for deserialization."""
        native = self._make_mock_native()
        channel = AsyncControlChannel(native)
        user_cb = MagicMock()
        channel.register_callback(42, user_cb)
        native.register_callback.assert_called_once()
        # The first arg should be the field number
        assert native.register_callback.call_args[0][0] == 42
        # The second arg should be a callable (bridge function)
        bridge = native.register_callback.call_args[0][1]
        assert callable(bridge)

        # Test the bridge function
        test_msg = pb.MessageV1()
        test_msg.id = "notify"
        bridge(test_msg.SerializeToString())
        user_cb.assert_called_once()
        received_msg = user_cb.call_args[0][0]
        assert received_msg.id == "notify"

    async def test_async_context_manager(self):
        """async with calls stop() on exit."""
        native = self._make_mock_native()
        async with AsyncControlChannel(native) as channel:
            assert channel.native is native
        native.stop.assert_called_once()


class TestAsyncControlChannelResultType:
    """Tests that AsyncControlChannel command methods return Result objects."""

    def _make_mock_native(self):
        """Create a mock NativeControlChannel."""
        native = MagicMock()
        native.remote_host.return_value = "127.0.0.1"
        native.remote_port.return_value = 5732
        native.is_connected.return_value = True
        native.is_running.return_value = False
        return native

    async def test_set_module_returns_result_on_success(self):
        """set_module() returns Result(ok=True) when native.set_module() returns True."""
        native = self._make_mock_native()
        native.set_module.return_value = True

        channel = AsyncControlChannel(native)
        result = await channel.set_module(pb.Module())

        assert isinstance(result, Result)
        assert result.ok is True

    async def test_set_module_returns_result_on_error(self):
        """set_module() returns Result(ok=False) when native.set_module() raises RuntimeError."""
        native = self._make_mock_native()
        native.set_module.side_effect = RuntimeError("config mismatch: unknown entity path")

        channel = AsyncControlChannel(native)
        result = await channel.set_module(pb.Module())

        assert isinstance(result, Result)
        assert result.ok is False
        assert "config mismatch" in result.error

    async def test_start_run_request_returns_result(self):
        """start_run_request() returns Result(ok=True) when native.start_run_request() succeeds."""
        native = self._make_mock_native()

        channel = AsyncControlChannel(native)
        result = await channel.start_run_request(pb.StartRunCommand())

        assert isinstance(result, Result)
        assert result.ok is True

    async def test_reset_returns_result(self):
        """reset() returns Result(ok=True) when native.reset() succeeds."""
        native = self._make_mock_native()

        channel = AsyncControlChannel(native)
        result = await channel.reset()

        assert isinstance(result, Result)
        assert result.ok is True

    async def test_authenticate_returns_result(self):
        """authenticate() returns Result(ok=True) when native.authenticate() returns True."""
        native = self._make_mock_native()
        native.authenticate.return_value = True

        channel = AsyncControlChannel(native)
        result = await channel.authenticate("my-token")

        assert isinstance(result, Result)
        assert result.ok is True


class TestBusyWaitRetryLogic:
    """When the proxy returns busy_response, the channel polls with PingCommand until the session becomes active, then re-sends the original command."""

    def _make_mock_native(self):
        """Create a minimal mock NativeControlChannel."""
        native = MagicMock()
        native.remote_host.return_value = "127.0.0.1"
        native.remote_port.return_value = 5732
        native.is_connected.return_value = True
        native.is_running.return_value = False
        return native

    @staticmethod
    def _busy_bytes() -> bytes:
        """Return serialized MessageV1 with busy_response set."""
        msg = pb.MessageV1(id="busy-id")
        msg.busy_response.CopyFrom(pb.DeviceBusyMessage())
        return msg.SerializeToString()

    @staticmethod
    def _success_bytes() -> bytes:
        """Return serialized MessageV1 with success_message set."""
        msg = pb.MessageV1(id="ok-id")
        msg.success_message.CopyFrom(pb.SuccessMessage())
        return msg.SerializeToString()

    @staticmethod
    def _reset_response_bytes() -> bytes:
        """Return serialized MessageV1 with reset_response set."""
        msg = pb.MessageV1(id="reset-id")
        msg.reset_response.CopyFrom(pb.ResetResponse())
        return msg.SerializeToString()

    async def test_send_and_recv_retries_on_busy_response(self):
        """send_and_recv() transparently handles busy→ping→ping→retry with exactly 4 native calls."""
        native = self._make_mock_native()
        native.send_and_recv.side_effect = [
            self._busy_bytes(),        # call 1: original cmd → busy
            self._busy_bytes(),        # call 2: first ping → still busy
            self._success_bytes(),     # call 3: second ping → active
            self._reset_response_bytes(),  # call 4: re-sent original → success
        ]

        channel = AsyncControlChannel(native)
        msg = pb.MessageV1(id="test-uuid")
        msg.reset_command.CopyFrom(pb.ResetCommand())
        result = await channel.send_and_recv(msg)

        assert result.HasField("reset_response")
        assert native.send_and_recv.call_count == 4, (
            f"Expected exactly 4 send_and_recv calls (1 original + 2 pings + 1 retry), "
            f"got {native.send_and_recv.call_count}"
        )

    async def test_send_and_recv_raises_on_busy_timeout(self):
        """send_and_recv() raises TimeoutError when the proxy never becomes available within max_busy_wait."""
        native = self._make_mock_native()
        native.send_and_recv.side_effect = lambda data, timeout: self._busy_bytes()

        channel = AsyncControlChannel(native, max_busy_wait=2.0)
        msg = pb.MessageV1(id="test-uuid")
        msg.reset_command.CopyFrom(pb.ResetCommand())
        with pytest.raises((TimeoutError, asyncio.TimeoutError)):
            await channel.send_and_recv(msg)

        assert native.send_and_recv.call_count > 1, (
            "At least one PingCommand should have been sent before timing out"
        )

    async def test_send_and_recv_no_retry_on_normal_response(self):
        """send_and_recv() does not retry when the first response is a normal response."""
        native = self._make_mock_native()
        native.send_and_recv.return_value = self._reset_response_bytes()

        channel = AsyncControlChannel(native)
        msg = pb.MessageV1(id="test-uuid")
        msg.reset_command.CopyFrom(pb.ResetCommand())
        result = await channel.send_and_recv(msg)

        assert native.send_and_recv.call_count == 1, (
            f"Expected exactly 1 send_and_recv call for a normal response, "
            f"got {native.send_and_recv.call_count}"
        )
        assert result.HasField("reset_response")

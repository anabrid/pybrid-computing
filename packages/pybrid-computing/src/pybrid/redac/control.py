# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""Async wrapper around the native C++ ControlChannel.

The native ControlChannel exposes blocking methods that release the Python GIL.
This module wraps those methods with asyncio-compatible coroutines using
``asyncio.loop.run_in_executor()``.

Each :class:`AsyncControlChannel` instance owns a dedicated
``ThreadPoolExecutor(max_workers=1)`` to avoid exhausting the default asyncio
executor when multiple channels run concurrently.
"""

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable
from uuid import uuid4

import pybrid.base.proto.main_pb2 as pb
from pybrid.base.result import Result
from pybrid.redac.entities import Path

logger = logging.getLogger(__name__)

from pybrid.native import ControlChannel as NativeControlChannel


class AsyncControlChannel:
    """Async wrapper around the native C++ ControlChannel.

    The C++ ControlChannel performs all blocking I/O on its own receive thread
    and releases the GIL on every blocking call.  This wrapper offloads those
    blocking calls to a dedicated ``ThreadPoolExecutor`` so that the asyncio
    event loop is never stalled.

    Each instance owns exactly **one** background thread (``max_workers=1``)
    so that concurrent callers each have their own serialised executor and
    the default asyncio executor is not exhausted.

    Typical usage::

        async with await AsyncControlChannel.create("192.168.1.1", 5732) as ch:
            ch.start()
            spec = await ch.extract(specification=True, recursive=True)
            config = await ch.extract("/", configuration=True)
    """

    def __init__(
        self,
        native: "NativeControlChannel",
        max_busy_wait: float = 30.0,
    ):
        """
        Args:
            native:        A connected ``NativeControlChannel`` instance.
            max_busy_wait: Maximum time in seconds to wait when a ``busy_response``
                           is received before raising :class:`TimeoutError`.
        """
        self._native = native
        self._max_busy_wait = max_busy_wait
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="ctrl-channel",
        )

    @classmethod
    async def create(
        cls,
        host: str,
        port: int,
        timeout: float = 5.0,
    ) -> "AsyncControlChannel":
        """Create and connect an :class:`AsyncControlChannel`.

        Uses the default executor for the TCP connect so the event loop is not blocked.
        """
        loop = asyncio.get_running_loop()
        native = await loop.run_in_executor(
            None,
            NativeControlChannel.create,
            host,
            port,
            timeout,
        )
        return cls(native)

    def start(self) -> None:
        """Start the C++ receive thread (non-blocking)."""
        self._native.start()

    async def stop(self) -> None:
        """Stop the receive thread, close transport, and shut down the executor."""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(self._executor, self._native.stop)
        self._executor.shutdown(wait=False)

    @property
    def remote_host(self) -> str:
        """Remote IP address, or an empty string when not connected."""
        return self._native.remote_host()

    @property
    def remote_port(self) -> int:
        """Remote TCP port, or ``0`` when not connected."""
        return self._native.remote_port()

    @property
    def is_connected(self) -> bool:
        """``True`` if the underlying TCPTransport is connected."""
        return self._native.is_connected()

    @property
    def is_running(self) -> bool:
        """``True`` if the C++ recv thread is active."""
        return self._native.is_running()

    async def send(self, msg: pb.MessageV1) -> None:
        """Fire-and-forget send — queues the serialized message for async TCP transmission."""
        self._native.send(msg.SerializeToString())

    async def _raw_send_and_recv(
        self,
        msg: pb.MessageV1,
        timeout: float = 5.0,
    ) -> pb.MessageV1:
        """Low-level send + receive without busy-wait retry logic.

        Factored out from :meth:`send_and_recv` so the busy-wait loop can
        call it without infinite recursion.
        """
        data = msg.SerializeToString()
        loop = asyncio.get_running_loop()
        response_bytes = await loop.run_in_executor(
            self._executor,
            self._native.send_and_recv,
            data,
            timeout,
        )
        response = pb.MessageV1()
        response.ParseFromString(response_bytes)
        return response

    async def send_and_recv(
        self,
        msg: pb.MessageV1,
        timeout: float = 5.0,
    ) -> pb.MessageV1:
        """Send a request and await the matching response.

        If the proxy returns a ``busy_response``, polls with
        :class:`pb.PingCommand` every second until the session becomes active,
        then re-sends the original message.

        :raises TimeoutError: If the device remains busy longer than
            ``max_busy_wait`` seconds.
        """
        response = await self._raw_send_and_recv(msg, timeout)

        if response.HasField("busy_response"):
            logger.info("Device busy, waiting for session to become active...")
            start_time = time.monotonic()
            while True:
                elapsed = time.monotonic() - start_time
                if elapsed >= self._max_busy_wait:
                    logger.warning("Device busy timeout after %.1fs (max_busy_wait=%.1fs)", elapsed, self._max_busy_wait)
                    raise TimeoutError(
                        f"Device busy for {elapsed:.1f}s, exceeded max wait "
                        f"of {self._max_busy_wait}s"
                    )
                await asyncio.sleep(1.0)
                ping_msg = self._new_message(pb.PingCommand())
                ping_response = await self._raw_send_and_recv(ping_msg, timeout)
                if ping_response.HasField("busy_response"):
                    logger.info("Still waiting... (%.0fs elapsed)", time.monotonic() - start_time)
                else:
                    logger.info("Session active, proceeding.")
                    break
            response = await self._raw_send_and_recv(msg, timeout)

        return response

    def register_callback(self, field_number: int, callback: Callable) -> None:
        """Register a callback for a specific message field number.

        The native layer invokes the callback from its C++ recv thread.  This
        bridge deserializes the raw bytes and marshals the call onto the asyncio
        event loop via ``call_soon_threadsafe()`` so *callback* can safely
        interact with asyncio primitives.

        The callback signature must be::

            def callback(msg: pb.MessageV1) -> None:
                ...
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        def _bridge(msg_bytes: bytes) -> None:
            msg = pb.MessageV1()
            msg.ParseFromString(msg_bytes)
            if loop is not None and loop.is_running():
                loop.call_soon_threadsafe(callback, msg)
            else:
                callback(msg)

        self._native.register_callback(field_number, _bridge)

    def unregister_callback(self, field_number: int) -> None:
        self._native.unregister_callback(field_number)

    @staticmethod
    def _new_message(body) -> pb.MessageV1:
        """Build a :class:`pb.MessageV1` wrapping *body* in the correct oneof field."""
        msg = pb.MessageV1(id=str(uuid4()))
        fields = msg.DESCRIPTOR.oneofs_by_name["kind"].fields
        for field in fields:
            if field.message_type == body.DESCRIPTOR:
                getattr(msg, field.name).CopyFrom(body)
                return msg
        raise ValueError(f"No MessageV1 oneof field for {type(body).__name__}")

    @staticmethod
    def _to_result(response: pb.MessageV1) -> Result:
        """Convert a response message to a :class:`~pybrid.base.result.Result`."""
        if response.HasField("error_message"):
            return Result.failure(response.error_message.description)
        return Result.success()

    async def extract(
        self,
        path: "str | Path | None" = None,
        *,
        recursive: bool = True,
        specification: bool = False,
        configuration: bool = False,
        calibration: bool = False,
        timeout: float = 5.0,
    ) -> pb.Module:
        cmd = pb.ExtractCommand(
            recursive=recursive,
            specification=specification,
            configuration=configuration,
            calibration=calibration,
        )
        if path is not None:
            cmd.entity.path = str(path)
        msg = self._new_message(cmd)
        response = await self.send_and_recv(msg, timeout)
        self._to_result(response).raise_on_error()
        return response.extract_response.module

    async def set_module(
        self,
        module: pb.Module,
        timeout: float = 5.0,
    ) -> Result:
        """Send a ``ConfigCommand`` with *module* and return the outcome."""
        
        cmd = pb.ConfigCommand()
        cmd.module.CopyFrom(module)
        msg = self._new_message(cmd)
        response = await self.send_and_recv(msg, timeout)
        return self._to_result(response)

    async def start_run_request(
        self,
        run_command: pb.StartRunCommand,
        timeout: float = 5.0,
    ) -> Result:
        """Send a ``StartRunCommand`` and wait for run-accepted acknowledgement.

        Does **not** wait for the run to complete.
        """
        msg = self._new_message(run_command)
        response = await self.send_and_recv(msg, timeout)
        return self._to_result(response)

    async def calibrate(
        self,
        leader: str = "",
        math: bool = False,
        gain: bool = False,
        offset: bool = False,
        timeout: float = 5.0,
    ) -> Result:
        cmd = pb.CalibrationCommand()
        cfg = cmd.config
        if leader:
            cfg.leader.path = leader
        cfg.math = pb.CalibrationConfig.Enabled if math else pb.CalibrationConfig.Disabled
        cfg.gain = pb.CalibrationConfig.Enabled if gain else pb.CalibrationConfig.Disabled
        cfg.offset = pb.CalibrationConfig.Enabled if offset else pb.CalibrationConfig.Disabled
        msg = self._new_message(cmd)
        response = await self.send_and_recv(msg, timeout)
        return self._to_result(response)

    async def register_external_entities(
        self,
        entities: dict[str, tuple[int, int, int, int]],
        timeout: float = 5.0,
    ) -> Result:
        """Send a ``RegisterExternalEntitiesCommand`` with the given entity map.

        Args:
            entities: Mapping of carrier MAC to IP address octets.
            timeout:  Send/recv timeout in seconds.
        """
        cmd = pb.RegisterExternalEntitiesCommand()
        for mac, ip_octets in entities.items():
            addr = pb.Address(data=bytes(ip_octets))
            cmd.entities[mac].CopyFrom(addr)
        msg = self._new_message(cmd)
        response = await self.send_and_recv(msg, timeout)
        return self._to_result(response)

    async def reset(
        self,
        *,
        keep_calibration: bool = True,
        sync: bool = True,
        timeout: float = 5.0,
    ) -> Result:
        cmd = pb.ResetCommand(keep_calibration=keep_calibration, sync=sync)
        msg = self._new_message(cmd)
        response = await self.send_and_recv(msg, timeout)
        return self._to_result(response)

    async def authenticate(self, token: str, timeout: float = 5.0) -> Result:
        cmd = pb.AuthRequest()
        cmd.bearer.token = token
        msg = self._new_message(cmd)
        response = await self.send_and_recv(msg, timeout)
        return self._to_result(response)

    @property
    def transport(self):
        """Underlying TCPTransport, shared with DataChannel for TCP fallback streaming."""
        return self._native.transport()

    @property
    def native(self) -> "NativeControlChannel":
        """Direct access to the C++ object for advanced use cases."""
        return self._native

    async def __aenter__(self) -> "AsyncControlChannel":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.stop()

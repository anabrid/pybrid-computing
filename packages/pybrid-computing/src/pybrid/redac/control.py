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
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

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
    ):
        """
        Args:
            native: A connected ``NativeControlChannel`` instance.
        """
        self._native = native
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

    async def reconnect(
        self,
        *,
        interval: float = 0.5,
        timeout: float | None = None,
    ) -> bool:
        """Reconnect the underlying transport to the cached endpoint.

        Offloads the blocking native reconnect call to the dedicated executor.
        Honours :class:`asyncio.CancelledError` by calling ``cancel_reconnect``
        on the native channel so Ctrl-C during a 20 s reconnect loop returns
        promptly.

        Args:
            interval: Poll interval between reconnect attempts, in seconds.
            timeout:  Total deadline for the reconnect. ``None`` means retry
                      forever (subject to cancellation).

        Returns:
            ``True`` if the channel reconnected, ``False`` on timeout or
            cancellation.
        """
        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(
            self._executor,
            self._native.reconnect,
            interval,
            timeout,
        )
        try:
            return await future
        except asyncio.CancelledError:
            # Ctrl-C or caller cancellation: unstick the native reconnect loop
            # so the executor thread frees up before we return.
            self._native.cancel_reconnect()
            try:
                await future
            except (asyncio.CancelledError, Exception):
                pass
            return False

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
        loop = asyncio.get_running_loop()
        response_bytes = await loop.run_in_executor(
            self._executor,
            self._native.extract,
            str(path) if path is not None else "",
            recursive,
            specification,
            configuration,
            calibration,
            timeout,
        )
        module = pb.Module()
        module.ParseFromString(response_bytes)
        return module

    async def set_module(
        self,
        module: pb.Module,
        timeout: float = 5.0,
    ) -> Result:
        """Send a ``ConfigCommand`` with *module* and return the outcome."""
        loop = asyncio.get_running_loop()
        try:
            success = await loop.run_in_executor(
                self._executor,
                self._native.set_module,
                module.SerializeToString(),
                timeout,
            )
            return Result.success() if success else Result.failure("set_module rejected")
        except RuntimeError as e:
            return Result.failure(str(e))

    async def start_run_request(
        self,
        run_command: pb.StartRunCommand,
        timeout: float = 5.0,
    ) -> Result:
        """Send a ``StartRunCommand`` and wait for run-accepted acknowledgement.

        Does **not** wait for the run to complete.
        """
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(
                self._executor,
                self._native.start_run_request,
                run_command.SerializeToString(),
                timeout,
            )
            return Result.success()
        except RuntimeError as e:
            return Result.failure(str(e))

    async def calibrate(
        self,
        leader: str = "",
        math: bool = False,
        gain: bool = False,
        offset: bool = False,
        timeout: float = 5.0,
    ) -> Result:
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(
                self._executor,
                self._native.calibrate,
                leader,
                math,
                gain,
                offset,
                timeout,
            )
            return Result.success()
        except RuntimeError as e:
            return Result.failure(str(e))

    async def reset(
        self,
        *,
        keep_calibration: bool = True,
        sync: bool = True,
        timeout: float = 5.0,
    ) -> Result:
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(
                self._executor,
                self._native.reset,
                keep_calibration,
                sync,
                timeout,
            )
            return Result.success()
        except RuntimeError as e:
            return Result.failure(str(e))

    async def authenticate(self, token: str, timeout: float = 5.0) -> Result:
        loop = asyncio.get_running_loop()
        try:
            success = await loop.run_in_executor(
                self._executor,
                self._native.authenticate,
                token,
                timeout,
            )
            return Result.success() if success else Result.failure("authentication rejected")
        except RuntimeError as e:
            return Result.failure(str(e))

    async def update_begin(
        self,
        new_size: int,
        new_sha256: str,
        timeout: float = 5.0,
        verbose: bool = False,
    ) -> int:
        """Begin an OTA update and return the chunk size advertised by the device.

        Args:
            new_size:   Total size of the firmware image in bytes.
            new_sha256: Hex-encoded SHA-256 digest of the firmware image.
            timeout:    Maximum time to wait for the acknowledgement in seconds.
            verbose:    Print progress information to stderr.

        Returns:
            The maximum chunk size (in bytes) the device will accept per write.

        :raises RuntimeError: On timeout, error response, or missing acknowledgement.
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self._executor,
            self._native.update_begin,
            new_size,
            new_sha256,
            timeout,
            verbose,
        )

    async def update_write_full(
        self,
        new_size: int,
        max_chunk_size: int,
        data: "bytes | bytearray | memoryview",
        timeout: float = 5.0,
        verbose: bool = False,
    ) -> Result:
        """Stream the firmware image to the device in chunks.

        Args:
            new_size:       Total size of the firmware image in bytes.
            max_chunk_size: Maximum chunk size advertised by :meth:`update_begin`.
            data:           Byte buffer holding the firmware image. Any object
                            implementing the Python buffer protocol is accepted.
            timeout:        Per-chunk timeout in seconds.
            verbose:        Print a progress bar to stderr.
        """
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(
                self._executor,
                self._native.update_write_full,
                new_size,
                max_chunk_size,
                data,
                timeout,
                verbose,
            )
            return Result.success()
        except RuntimeError as e:
            return Result.failure(str(e))

    async def update_verify(self, timeout: float = 5.0, verbose: bool = False) -> Result:
        """Ask the device to verify the uploaded image against the SHA-256 digest."""
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(
                self._executor,
                self._native.update_verify,
                timeout,
                verbose,
            )
            return Result.success()
        except RuntimeError as e:
            return Result.failure(str(e))

    async def update_commit(self, timeout: float = 5.0, verbose: bool = False) -> Result:
        """Commit the verified update; the device reboots into the new image."""
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(
                self._executor,
                self._native.update_commit,
                timeout,
                verbose,
            )
            return Result.success()
        except RuntimeError as e:
            return Result.failure(str(e))

    async def update_abort(self, timeout: float = 5.0) -> Result:
        """Abort an in-progress update and discard any uploaded data."""
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(
                self._executor,
                self._native.update_abort,
                timeout,
            )
            return Result.success()
        except RuntimeError as e:
            return Result.failure(str(e))

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

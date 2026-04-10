# Copyright (c) 2022-2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""Self-contained client connection for DummyDAC mock server.

This module replaces the Protocol + PassthroughTransport combination with a
single :class:`ClientConnection` class that handles varint-framed protobuf
messaging over asyncio StreamReader/StreamWriter directly.
"""

import asyncio
import logging
from asyncio import StreamReader, StreamWriter
from ipaddress import IPv4Address
from typing import Callable
from uuid import UUID, uuid4

from google.protobuf.internal import encoder as _pb_encoder
from google.protobuf.json_format import MessageToJson

import pybrid.base.proto.main_pb2 as pb

logger = logging.getLogger(__name__)

# Varint encoder from protobuf internals.  Calling it as:
#   _varint_encoder(writer_method, value)
# writes the varint-encoded *value* using *writer_method*.
_varint_encoder = _pb_encoder._VarintEncoder()


def get_message_kind(msg: pb.MessageV1) -> str | None:
    """Return the name of the oneof field set in *msg*, or None.

    This is the server-side counterpart to the same helper in Protocol.

    :param msg: A :class:`pb.MessageV1` instance, or ``None``.
    :return: The field name of the active oneof variant, or ``None``.
    """
    if msg is None:
        return None
    kind = msg.WhichOneof("kind")
    return kind


class _UDPSender:
    """Minimal async UDP sender wrapping an asyncio.DatagramTransport.

    Used by :class:`UDPStreamingHandler` to give :class:`ClientConnection`
    a ``send_packet(data)`` interface for routing run data over UDP.

    :param transport: A connected asyncio DatagramTransport.
    """

    def __init__(self, transport: asyncio.DatagramTransport) -> None:
        """
        Initialise the UDP sender.

        :param transport: A connected :class:`asyncio.DatagramTransport`.
        """
        self._transport = transport

    async def send_packet(self, data: bytes) -> None:
        """Send *data* as a UDP datagram.

        :param data: Raw bytes to transmit.
        """
        self._transport.sendto(data)

    def close(self) -> None:
        """Close the underlying datagram transport."""
        self._transport.close()


# Message types that are routed through data_transport when available.
_RUN_DATA_KINDS = frozenset({
    "run_data_message",
    "run_data_end_message",
    "run_state_change_message",
})


class ClientConnection:
    """Varint-framed protobuf connection for a single DummyDAC client.

    Replaces the :class:`~pybrid.base.transport.passthrough.PassthroughTransport`
    + :class:`~pybrid.redac.protocol.protocol.Protocol` combination.  It reads
    directly from an asyncio :class:`~asyncio.StreamReader` / writes to a
    :class:`~asyncio.StreamWriter`, handling varint framing and Envelope
    serialisation internally.

    Usage (from DummyDAC._client_connected)::

        connection = ClientConnection(reader, writer)
        connection.register_callback(field_number, handler.handle,
                                     extra_args=[connection])
        async with connection:
            await connection  # wait until client disconnects

    :param reader: The asyncio StreamReader for the accepted connection.
    :param writer: The asyncio StreamWriter for the accepted connection.
    """

    def __init__(self, reader: StreamReader, writer: StreamWriter) -> None:
        """
        Initialise the connection.

        :param reader: The asyncio :class:`~asyncio.StreamReader`.
        :param writer: The asyncio :class:`~asyncio.StreamWriter`.
        """
        self._reader = reader
        self._writer = writer
        self._callbacks: dict[int, tuple[Callable, list, dict]] = {}
        self._warned_unknown: set[str] = set()
        self._recv_task: asyncio.Task | None = None
        #: Optional UDP sender set by UDPStreamingHandler.
        self.data_transport: _UDPSender | None = None

    @staticmethod
    def new_message(body, id=None) -> pb.MessageV1:  # noqa: A002
        """Wrap *body* in a :class:`pb.MessageV1` and assign an *id*.

        Mirrors the original ``Protocol.new_message`` static method so that
        handler code can be migrated with minimal changes.

        :param body: A protobuf message to embed in the ``kind`` oneof.
        :param id: Optional message ID.  If ``None``, a new UUID is generated.
                   Pass ``id=None`` explicitly for notifications (server-push).
        :return: A fully populated :class:`pb.MessageV1`.
        :raises ValueError: If no oneof field matches *body*'s descriptor.
        """
        if id is None:
            id = uuid4()  # noqa: A001

        if isinstance(id, UUID):
            id = str(id)  # noqa: A001

        msg = pb.MessageV1(id=id)
        fields = msg.DESCRIPTOR.oneofs_by_name["kind"].fields
        for field in fields:
            if field.message_type == body.DESCRIPTOR:
                getattr(msg, field.name).CopyFrom(body)
                return msg
        raise ValueError(
            f"No MessageV1 oneof field for {type(body).__name__}"
        )

    def register_callback(
        self,
        msg_type: int,
        callback: Callable,
        extra_args: list | None = None,
        extra_kwargs: dict | None = None,
    ) -> None:
        """Register *callback* for incoming messages of type *msg_type*.

        :param msg_type: The field number (``pb.MessageV1.*_FIELD_NUMBER``).
        :param callback: Async callable ``(cmd, *extra_args, **extra_kwargs)``.
        :param extra_args: Additional positional arguments forwarded on call.
        :param extra_kwargs: Additional keyword arguments forwarded on call.
        """
        self._callbacks[msg_type] = (
            callback,
            extra_args or [],
            extra_kwargs or {},
        )

    async def send_message(self, msg: pb.MessageV1) -> None:
        """Serialise *msg* inside an Envelope and send it with a varint prefix.

        Run-data-related messages (``run_data_message``, ``run_data_end_message``,
        ``run_state_change_message``) are routed through :attr:`data_transport`
        when it is set; all other messages go over the control (TCP) writer.

        :param msg: The :class:`pb.MessageV1` to transmit.
        """
        logger.debug(
            "sending: %s",
            MessageToJson(msg, always_print_fields_with_no_presence=True),
        )
        envelope = pb.Envelope(message_v1=msg)
        data = envelope.SerializeToString()

        kind = msg.WhichOneof("kind")
        if kind in _RUN_DATA_KINDS and self.data_transport is not None:
            await self.data_transport.send_packet(data)
        else:
            _varint_encoder(self._writer.write, len(data))
            self._writer.write(data)
            await self._writer.drain()

    def get_remote_address(self) -> IPv4Address:
        """Return the IPv4 address of the connected client.

        :return: The remote :class:`~ipaddress.IPv4Address`.
        """
        peername = self._writer.get_extra_info("peername")
        return IPv4Address(peername[0])

    async def __aenter__(self) -> "ClientConnection":
        """Start the receive loop task.

        :return: *self* for use as context variable.
        """
        self._recv_task = asyncio.create_task(self._recv_loop())
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Stop the receive loop and close the connection."""
        await self.stop()

    def __await__(self):
        """Await the receive loop task (wait until client disconnects)."""
        if self._recv_task is None:
            raise RuntimeError(
                "ClientConnection must be started with 'async with' before awaiting."
            )
        return self._recv_task.__await__()

    async def stop(self) -> None:
        """Cancel the receive loop and close the writer."""
        if self._recv_task is not None and not self._recv_task.done():
            self._recv_task.cancel()
            try:
                await self._recv_task
            except (asyncio.CancelledError, Exception):
                pass
        self._recv_task = None
        try:
            self._writer.close()
            await self._writer.wait_closed()
        except (BrokenPipeError, ConnectionResetError, Exception):
            pass

    async def _recv_varint(self) -> int:
        """Decode a varint from the reader byte-by-byte.

        :return: The decoded unsigned integer length prefix.
        :raises EOFError: If the connection closes mid-varint.
        """
        shift = 0
        result = 0
        while True:
            b = await self._reader.read(1)
            if b == b"":
                raise EOFError("Unexpected EOF while reading varint")
            i = b[0]
            result |= (i & 0x7F) << shift
            if not (i & 0x80):
                break
            shift += 7
        return result

    async def _recv_loop(self) -> None:
        """Main receive loop: read varint-framed Envelope messages continuously.

        Exits silently on normal disconnection (EOFError, ConnectionError,
        IncompleteReadError).  Processing errors are logged but do not abort
        the loop.
        """
        try:
            while True:
                length = await self._recv_varint()
                data = await self._reader.readexactly(length)
                envelope = pb.Envelope()
                envelope.ParseFromString(data)

                # GenericMessage ping: respond at the Envelope level.
                if envelope.HasField("generic") and envelope.generic.HasField("ping_command"):
                    resp = pb.Envelope()
                    resp.generic.ping_response.CopyFrom(pb.PingResponse())
                    data = resp.SerializeToString()
                    _varint_encoder(self._writer.write, len(data))
                    self._writer.write(data)
                    await self._writer.drain()
                    continue

                msg = envelope.message_v1
                await self._process(msg)
        except (EOFError, ConnectionError, asyncio.IncompleteReadError):
            pass  # Normal client disconnect
        except asyncio.CancelledError:
            pass  # Stopped externally

    async def _process(self, msg: pb.MessageV1) -> None:
        """Dispatch an incoming message to the appropriate registered callback.

        - If ``msg.id`` is empty (notification): invoke callback, ignore return.
        - If ``msg.id`` is non-empty (request): invoke callback, send response.
        - On callback exception: send an :class:`pb.ErrorMessage` to the client.

        :param msg: The decoded :class:`pb.MessageV1`.
        """
        kind = get_message_kind(msg)
        if kind is None:
            logger.warning("Received message with no kind, ignoring.")
            return

        try:
            field = pb.MessageV1.DESCRIPTOR.fields_by_name[kind]
        except KeyError:
            logger.warning("Unknown message kind '%s', ignoring.", kind)
            return

        field_number = field.number
        if field_number not in self._callbacks:
            if kind not in self._warned_unknown:
                self._warned_unknown.add(kind)
                logger.warning(
                    "No callback registered for message type '%s'.", kind
                )
            return

        callback, extra_args, extra_kwargs = self._callbacks[field_number]
        body = getattr(msg, kind)

        is_notification = not msg.id

        try:
            response_body = await callback(body, *extra_args, **extra_kwargs)
        except Exception as exc:
            logger.exception("Error in callback for '%s': %s", kind, exc)
            if not is_notification:
                err_msg = ClientConnection.new_message(
                    pb.ErrorMessage(description=repr(exc)), id=msg.id
                )
                await self.send_message(err_msg)
            return

        if is_notification:
            # Notifications: ignore return value
            if response_body is not None:
                logger.debug(
                    "Return value of notification callback for '%s' is ignored.",
                    kind,
                )
            return

        # Request: send response
        if response_body is None:
            return

        if isinstance(response_body, pb.MessageV1):
            await self.send_message(response_body)
        else:
            response_msg = ClientConnection.new_message(response_body, id=msg.id)
            await self.send_message(response_msg)

# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import asyncio

from pybrid.base.transport.base import BaseTransport

import queue
import threading
import time

class UDPClientProtocol(asyncio.DatagramProtocol):
    packets : asyncio.Queue

    def __init__(self, packets : queue.Queue):
        self.packets = packets

    def datagram_received(self, data, addr):
        self.packets.put_nowait(data)

    def error_received(self, exc):
        print(f"Error received: {exc}")


class UDPTransport(BaseTransport):
    """A UDP/IP transport implementation for network communication."""
    packets: queue.Queue

    def __init__(self, transport, protocol, packets: asyncio.Queue, remote_addr=None):
        self.transport = transport
        self.protocol = protocol
        self.packets = packets
        self.remote_addr = remote_addr

    @classmethod
    async def create(cls, local_port=None, remote_host=None, remote_port=None):
        """
        Create a new :class:`UDPTransport` instance for communicating over network.

        :param local_port: Local network port to bind to.
        :param remote_host: Optional target hostname or IP address for sending.
        :param remote_port: Optional target network port for sending.
        :param kwargs: Keyword arguments are passed on to :class:`.BaseTransport`.
        :return: A :class:`UDPTransport` instance.
        """
        loop = asyncio.get_running_loop()
        packets = asyncio.Queue()

        # Set up remote address if provided
        remote_addr = None
        if remote_host and remote_port:
            remote_addr = (remote_host, remote_port)

        local_addr = ('0.0.0.0', local_port) if local_port else None

        transport, protocol = await loop.create_datagram_endpoint(
            lambda: UDPClientProtocol(packets),
            local_addr=local_addr,
            remote_addr=remote_addr  # Can be None for unconnected socket
        )

        return UDPTransport(
            transport=transport,
            protocol=protocol,
            packets=packets,
            remote_addr=remote_addr
        )

    async def send_packet(self, data: bytes) -> None:
        self.transport.sendto(data, self.remote_addr)

    async def receive_packet(self, timeout=3) -> bytes:
        packet = await self.packets.get()
        self.packets.task_done()
        return packet
    
    def close(self):
        """Close the UDP transport and release the port."""
        if self.transport:
            self.transport.close()

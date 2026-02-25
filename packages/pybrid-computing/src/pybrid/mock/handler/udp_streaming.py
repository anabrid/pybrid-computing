# Copyright (c) 2022-2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""Handler for the UDP streaming command."""

import asyncio
import logging
from typing import TYPE_CHECKING, Union

import pybrid.base.proto.main_pb2 as pb
from pybrid.mock.connection import ClientConnection, _UDPSender
from pybrid.mock.handler.base import BaseHandler

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class UDPStreamingHandler(BaseHandler):
    """
    Handler for UDP streaming commands.

    Sets up UDP data transport for sending run data to clients.
    """

    async def handle(
        self, cmd: pb.UdpDataStreamingCommand, connection: ClientConnection
    ) -> Union[pb.SuccessMessage, pb.ErrorMessage]:
        """
        Handle a UDP streaming command by setting up UDP data transport.

        If UDP streaming is enabled in the configuration, creates a UDP transport
        to send run data to the client's specified port. Otherwise, refuses the
        request with an error message.

        :param cmd: The UDP streaming command containing the client's UDP port.
        :param connection: The client connection instance.
        :return: SuccessMessage if accepted, ErrorMessage if refused.
        """
        logger.debug("UDP_STREAMING: Request to stream to client port %d", cmd.port)
        if not self.server.config.accept_udp_streaming:
            logger.debug("UDP_STREAMING: Refused (disabled in config)")
            return pb.UdpDataStreamingRefusedResponse()

        # Store client UDP port for this connection's data streaming
        self.server._client_udp_ports[connection] = cmd.port

        # Get the client's IP address from the connection's remote address
        client_ip = str(connection.get_remote_address())

        # Create an asyncio datagram endpoint for sending UDP data to the client.
        # The client is listening on cmd.port; we send to that address.
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(
            asyncio.DatagramProtocol,
            remote_addr=(client_ip, cmd.port),
        )
        connection.data_transport = _UDPSender(transport)

        logger.debug(
            "DummyDAC: UDP streaming configured for client %s on port %d",
            client_ip,
            cmd.port,
        )

        return pb.SuccessMessage()

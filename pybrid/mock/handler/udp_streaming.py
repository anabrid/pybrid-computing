# Copyright (c) 2022-2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""Handler for the UDP streaming command."""

import logging
from typing import TYPE_CHECKING, Union

import pybrid.base.proto.main_pb2 as pb
from pybrid.base.transport.udp import UDPTransport
from pybrid.mock.handler.base import BaseHandler

if TYPE_CHECKING:
    from pybrid.redac.protocol.protocol import Protocol

logger = logging.getLogger(__name__)


class UDPStreamingHandler(BaseHandler):
    """
    Handler for UDP streaming commands.

    Sets up UDP data transport for sending run data to clients.
    """

    async def handle(
        self, cmd: pb.UdpDataStreamingCommand, protocol: "Protocol"
    ) -> Union[pb.SuccessMessage, pb.ErrorMessage]:
        """
        Handle a UDP streaming command by setting up UDP data transport.

        If UDP streaming is enabled in the configuration, creates a UDP transport
        to send run data to the client's specified port. Otherwise, refuses the
        request with an error message.

        :param cmd: The UDP streaming command containing the client's UDP port.
        :param protocol: The protocol instance for this client connection.
        :return: SuccessMessage if accepted, ErrorMessage if refused.
        """
        logger.debug("UDP_STREAMING: Request to stream to client port %d", cmd.port)
        if not self.server.config.accept_udp_streaming:
            logger.debug("UDP_STREAMING: Refused (disabled in config)")
            return pb.ErrorMessage(description="UDP streaming disabled")

        # Store client UDP port for this protocol's data streaming
        self.server._client_udp_ports[protocol] = cmd.port

        # Get the client's IP address from the protocol's remote address
        client_ip = str(protocol.get_remote_address())

        # Create UDP transport to client for sending run data
        # The client is listening on cmd.port, we connect to it
        udp_transport = await UDPTransport.create(
            local_port=None,
            remote_host=client_ip,
            remote_port=cmd.port
        )
        protocol.data_transport = udp_transport

        logger.debug(
            "DummyDAC: UDP streaming configured for client %s on port %d",
            client_ip,
            cmd.port
        )

        return pb.SuccessMessage()

# Copyright (c) 2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""Native high-performance transport layer.

This module provides C++ implementations of UDP and TCP transports
using standalone ASIO for networking.
"""

import asyncio

try:
    from pybrid.native._impl import (  # Constants; Enums; Exceptions; Structs; Classes  # Constants; Enums; Exceptions; Structs; Classes  # Constants; Enums; Exceptions; Structs; Classes  # Constants; Enums; Exceptions; Structs; Classes  # Constants; Enums; Exceptions; Structs; Classes  # Constants; Enums; Exceptions; Structs; Classes  # Constants; Enums; Exceptions; Structs; Classes  # Constants; Enums; Exceptions; Structs; Classes  # Constants; Enums; Exceptions; Structs; Classes  # Constants; Enums; Exceptions; Structs; Classes  # Constants; Enums; Exceptions; Structs; Classes  # Constants; Enums; Exceptions; Structs; Classes  # Constants; Enums; Exceptions; Structs; Classes  # Constants; Enums; Exceptions; Structs; Classes  # Constants; Enums; Exceptions; Structs; Classes  # Constants; Enums; Exceptions; Structs; Classes
        DEFAULT_TCP_CONNECT_TIMEOUT,
        DEFAULT_TCP_MESSAGE_SIZE,
        MAX_UDP_PACKET_SIZE,
        AcceptedSocket,
        BufferFullError,
        BufferType,
        ControlChannel,
        DataChannel,
        LockFreeBuffer,
        MessageTooLargeError,
        ProxyServer,
        RecvResult,
        RecvStatus,
        RunState,
        SampleDecodingDataChannel,
        SampleLockFreeBuffer,
        TCPStats,
        TCPTransport,
        UDPSocket,
        UDPStats,
    )
    from pybrid.native._impl import TCPServer as _TCPServerImpl

    class TCPServer(_TCPServerImpl):
        """
        TCP server wrapper that adds async serve_forever() method.

        Inherits all functionality from the native TCPServer and adds
        asyncio-compatible serve_forever() for CLI compatibility.
        """

        async def serve_forever(self):
            """
            Wait until the server is stopped.

            This is an asyncio-compatible method that blocks until
            stop() is called, typically via Ctrl+C or shutdown signal.
            """
            while self.is_running():
                await asyncio.sleep(0.1)

    # Backward compatibility aliases (deprecated)
    UDPServer = UDPSocket  # Deprecated: use UDPSocket instead
    UDPTransport = UDPSocket  # Deprecated: use UDPSocket instead
    NATIVE_AVAILABLE = True
except ImportError as e:
    NATIVE_AVAILABLE = False
    _import_error = e

__all__ = [
    "NATIVE_AVAILABLE",
    "ControlChannel",
    "BufferType",
    "RecvStatus",
    "RunState",
    "RecvResult",
    "UDPStats",
    "TCPStats",
    "AcceptedSocket",
    "UDPSocket",
    "UDPServer",  # Deprecated: backward compatibility alias for UDPSocket
    "UDPTransport",  # Deprecated: backward compatibility alias for UDPSocket
    "TCPTransport",
    "TCPServer",
    "DataChannel",
    "SampleDecodingDataChannel",
    "LockFreeBuffer",
    "SampleLockFreeBuffer",
    "ProxyServer",
    "MessageTooLargeError",
    "BufferFullError",
    "MAX_UDP_PACKET_SIZE",
    "DEFAULT_TCP_MESSAGE_SIZE",
    "DEFAULT_TCP_CONNECT_TIMEOUT",
]

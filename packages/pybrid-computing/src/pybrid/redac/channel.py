# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""Device connection grouping control and data channels."""

from dataclasses import dataclass
from typing import Any

from pybrid.native import SampleDecodingDataChannel

ControlChannel = Any


@dataclass(eq=False)
class DeviceConnection:
    """Groups control and data channels for one device (or shared for proxy).

    ``eq=False`` preserves identity-based equality and hashing so that
    instances can be stored in :class:`set` collections (as used by
    :meth:`~pybrid.redac.connection.ConnectionManager.get_unique_connections`).

    Attributes:
        control: Control channel for sending configuration and commands.
            May be ``None`` in environments without the native C++ extension.
        data: Data channel for receiving decoded sample data.
            May be ``None`` when data streaming is not yet initialised.
        output_queue: IBuffer holding decoded sample blobs produced by the data
            channel.  Kept here to prevent garbage collection of the C++ object.
    """

    control: ControlChannel
    data: SampleDecodingDataChannel
    output_queue: Any = None

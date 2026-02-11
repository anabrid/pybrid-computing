# Copyright (c) 2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
LUCIDAC-specific controller extending the REDAC base controller.

Key differences from the REDAC controller:
- Initializes ``self.computer`` as a :class:`LUCIStack` (not plain REDAC).
- Does not run a proxy, so virtual MACs must be mapped manually.
- Supports ACL inputs/outputs via the carrier's front plane.
"""

import logging
import typing

from pybrid.redac.computer import REDAC
from pybrid.lucidac.computer import LUCIStack
from pybrid.redac.controller import Controller as REDACController
from pybrid.redac.protocol.protocol import Protocol

logger = logging.getLogger(__name__)

class Controller(REDACController):
    """
    A minimal controller that implements changes to the REDAC controller
    that are required to support a LUCIDAC natively.

    These changes are:
    - no running proxy, hence the device does not understand virtual MACs
      such as '00-00-00-00-00-00' but physical MACs such as
      '04-E9-E5-15-87-A0' -- the configuration files use the virtual MAC
      and this controller performs the mapping.
    - availability of ACL inputs/outputs via the carrier's front plane.
    """

    def __init__(self, standalone: bool = False):
        """Initialize the LUCIDAC controller, delegating to the REDAC parent.

        After the parent creates a plain REDAC computer, we replace it with
        a LUCIStack so that LUCIDAC-specific serialization is used.

        :param standalone: Whether this controller operates in standalone mode.
        """
        super().__init__(standalone=standalone)
        self.computer = LUCIStack(entities=[])

    @classmethod
    def get_protocol_implementation(cls):
        """Return the specific :class:`.Protocol` implementation for this device."""
        return Protocol

    async def add_device(self, host, port, name=None):
        """
        Add a LUCIDAC endpoint (direct or proxy) to this controller.

        Delegates to the REDAC base class, then verifies that the call
        registered at least one new carrier and exactly one new protocol
        connection.  In proxy mode a single call may register multiple
        carriers; in direct mode it registers exactly one.

        :param host: Hostname or IP address of the LUCIDAC endpoint.
        :param port: TCP port number.
        :param name: Optional human-readable name for the connection.
        :raises Exception: If the expected number of carriers or protocols
            was not registered.
        """
        prev_devices = len(self.devices)
        prev_protos = len(self.protocols)

        await super().add_device(host, port, name=name)

        new_devices = len(self.devices) - prev_devices
        new_protos = len(self.protocols) - prev_protos
        if new_devices < 1 or new_protos != 1:
            raise Exception(
                f"Failed adding LUCIDAC {host}:{port} "
                f"(new carriers={new_devices}, new protocols={new_protos})"
            )

        # Log every newly discovered carrier MAC.
        for path in list(self.devices.keys())[prev_devices:]:
            logger.info("LUCIDAC carrier MAC: %s", str(path))

    async def set_computer(self, computer: REDAC):
        """
        Override REDAC method for setting configs.

        Passes the provided ``computer`` argument to the parent (not
        ``self.computer``), fixing the previous bug where the argument
        was ignored.

        :param computer: The computer configuration to set.
        """
        await super().set_computer(computer)

    async def stop(self):
        """Stop all protocol connections managed by this controller."""
        for protocol in self.protocols.keys():
            await protocol.stop()

# Copyright (c) 2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
LUCIDAC-specific controller extending the REDAC base controller.

Key differences from the REDAC controller:
- Initializes ``self.computer`` as a :class:`LUCIStack` (not plain REDAC).
- Does not run a proxy, so virtual MACs must be mapped manually.
- Supports ACL inputs/outputs via the carrier's front plane.
- Always uses NATIVE sync (LUCIDAC hardware has no USB-SPI sync path).
"""

import logging
import warnings

from pybrid.lucidac.computer import LUCIStack
from pybrid.redac.computer import REDAC
from pybrid.redac.controller import Controller as REDACController

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
    - always uses NATIVE sync (LUCIDAC hardware has no USB-SPI controller).
    """

    def __init__(self, **kwargs):
        """Initialize the LUCIDAC controller, delegating to the REDAC parent.

        After the parent creates a plain REDAC computer, we replace it with
        a LUCIStack so that LUCIDAC-specific serialization is used.

        LUCIDAC always uses NATIVE sync.  Any ``standalone`` or ``sync_impl``
        keyword arguments are accepted for backward compatibility but ignored
        with a deprecation warning.
        """
        if "standalone" in kwargs or "sync_impl" in kwargs:
            warnings.warn(
                "The 'standalone' and 'sync_impl' parameters are ignored by "
                "the LUCIDAC controller (always uses NATIVE sync).",
                DeprecationWarning,
                stacklevel=2,
            )

        super().__init__()
        self.computer = LUCIStack(entities=[])

    async def add_device(self, host, port):
        """
        Add a LUCIDAC endpoint (direct or proxy) to this controller.

        Delegates to the REDAC base class, then verifies that the call
        registered at least one new carrier connection using a delta-based
        assertion on :attr:`connection_manager.connections`.

        :param host: Hostname or IP address of the LUCIDAC endpoint.
        :param port: TCP port number.
        :param name: Optional human-readable name for the connection.
        :raises Exception: If the expected number of carriers was not registered.
        """
        prev_conns = len(self.connection_manager.connections)

        await super().add_device(host, port)

        new_conns = len(self.connection_manager.connections) - prev_conns
        if new_conns < 1:
            raise Exception(f"Failed adding LUCIDAC {host}:{port} " f"(new carriers={new_conns})")

        # Log every newly discovered carrier MAC.
        all_paths = list(self.connection_manager.connections.keys())
        for path in all_paths[prev_conns:]:
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

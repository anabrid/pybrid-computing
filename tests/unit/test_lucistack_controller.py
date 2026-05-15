# Copyright (c) 2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
Unit tests for LUCIDACController.

These tests verify that:
- set_computer() passes the argument to the parent (not self.computer).
"""

from unittest.mock import AsyncMock, patch

import pytest

from pybrid.lucidac.controller import Controller as LUCIStackController
from pybrid.redac.computer import REDAC
from pybrid.redac.entities import Loc

# Try importing the new name; fall back to old name so tests fail (not crash)
try:
    from pybrid.lucidac.computer import LUCIStack
except ImportError:
    from pybrid.lucidac.computer import LUCIDAC as LUCIStack


class TestSetComputerBugFix:
    """Tests verifying that set_computer() passes the argument, not self.computer."""

    @pytest.mark.asyncio
    async def test_set_computer_uses_argument(self):
        """set_computer(arg) must call super().set_computer(arg), not super().set_computer(self.computer)."""
        ctrl = LUCIStackController()

        # Build a LUCIStack with distinguishable content
        from pybrid.redac.blocks import CBlock, IBlock, UBlock
        from pybrid.redac.carrier import Carrier
        from pybrid.redac.cluster import Cluster
        from pybrid.redac.entities import Path

        mac = "AA-BB-CC-DD-EE-FF"
        carrier_path = Path.parse(mac)
        cluster_path = carrier_path / "0"
        cluster = Cluster(
            path=cluster_path,
            location=Loc.new_cluster(0, 0, 0),
            ublock=UBlock(path=cluster_path / "U"),
            cblock=CBlock(path=cluster_path / "C"),
            iblock=IBlock(path=cluster_path / "I"),
            shblock=None,
        )
        carrier = Carrier(
            path=carrier_path,
            location=Loc.new_carrier(0, 0),
            clusters=[cluster],
            tblock=None,
        )
        new_computer = LUCIStack(entities=[carrier])

        # Mock the grandparent's set_computer to capture the argument
        captured_args = []

        async def mock_set_computer(computer_arg):
            captured_args.append(computer_arg)

        with patch.object(
            REDAC.__mro__[0].__bases__[0] if hasattr(REDAC, "__mro__") else REDAC,
            "set_computer",
            side_effect=mock_set_computer,
            create=True,
        ):
            # Use a more direct approach: patch the REDACController.set_computer
            from pybrid.redac.controller import Controller as REDACController

            with patch.object(
                REDACController,
                "set_computer",
                new_callable=AsyncMock,
            ) as mock_parent_set:
                await ctrl.set_computer(new_computer)

                # The parent's set_computer must have been called with the
                # argument we passed, NOT with ctrl.computer
                mock_parent_set.assert_called_once()
                call_arg = mock_parent_set.call_args[0][0]

                assert call_arg is new_computer, (
                    f"set_computer() must pass the argument to super(), "
                    f"but it passed {call_arg!r} instead of the new_computer. "
                    f"This is the self.computer bug."
                )

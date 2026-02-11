# Copyright (c) 2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
Unit tests for LUCIDACController (Sprint 1 — controller fixes).

These tests verify that:
- LUCIDACController.__init__ calls super().__init__(), so self.computer
  is properly initialized as a LUCIStack(entities=[]) instance.
- REDAC parent attributes (protocols, runs, devices, etc.) are present
  after construction.
- set_computer() passes the argument to the parent (not self.computer).

These tests are written against the POST-refactoring interface and are
expected to FAIL against the current (pre-refactoring) codebase.
"""

import pytest
from unittest.mock import AsyncMock, patch

from pybrid.lucidac.controller import Controller as LUCIStackController
from pybrid.redac.computer import REDAC

# Try importing the new name; fall back to old name so tests fail (not crash)
try:
    from pybrid.lucidac.computer import LUCIStack
except ImportError:
    from pybrid.lucidac.computer import LUCIDAC as LUCIStack


class TestLUCIStackControllerInit:
    """Tests verifying that LUCIDACController.__init__ calls super().__init__()."""

    def test_init_creates_lucistack_computer(self):
        """After creating a LUCIStackController, self.computer must be a LUCIStack instance."""
        ctrl = LUCIStackController(standalone=True)

        # The controller must have a 'computer' attribute
        assert hasattr(ctrl, "computer"), (
            "LUCIStackController must have 'computer' attribute after __init__"
        )

        # The computer must be a LUCIStack (not a plain REDAC)
        # Post-refactoring: LUCIDAC is renamed to LUCIStack, which is the class
        # the controller should create.
        # Pre-refactoring: the controller does NOT call super().__init__(), so
        # self.computer does not exist, and this test will fail.
        computer = ctrl.computer
        assert isinstance(computer, LUCIStack), (
            f"Expected controller.computer to be a LUCIStack instance, "
            f"got {type(computer).__name__}"
        )

    def test_super_init_called(self):
        """Verify REDAC parent attributes exist after construction.

        When super().__init__() is called, the parent (REDACController)
        initializes protocols, runs, devices, _raw_entity_dict,
        _ongoing_runs, _clusters_per_carrier, sync, standalone, and
        _callbacks. These must all be present on the LUCIDACController.
        """
        ctrl = LUCIStackController(standalone=True)

        # All of these attributes are set by REDACController.__init__
        expected_attrs = [
            "computer",
            "devices",
            "protocols",
            "runs",
            "_raw_entity_dict",
            "_ongoing_runs",
            "_clusters_per_carrier",
            "sync",
            "standalone",
            "_callbacks",
        ]

        for attr in expected_attrs:
            assert hasattr(ctrl, attr), (
                f"LUCIStackController missing '{attr}' — super().__init__() "
                f"may not have been called"
            )

        # Additionally, self.computer must be initialized (not None)
        assert ctrl.computer is not None, (
            "controller.computer should not be None after __init__"
        )

        # computer.entities should be an empty list (no carriers yet)
        assert isinstance(ctrl.computer, LUCIStack), (
            f"controller.computer should be LUCIStack, got {type(ctrl.computer).__name__}"
        )


class TestSetComputerBugFix:
    """Tests verifying that set_computer() passes the argument, not self.computer."""

    @pytest.mark.asyncio
    async def test_set_computer_uses_argument(self):
        """Create controller, create a LUCIStack with a carrier, call
        set_computer(lucistack). Verify the argument was passed to the
        parent, not self.computer.

        The bug in the current code is:
            async def set_computer(self, computer):
                await super().set_computer(self.computer)  # wrong!
        It should be:
                await super().set_computer(computer)        # correct
        """
        ctrl = LUCIStackController(standalone=True)

        # Build a LUCIStack with distinguishable content
        from pybrid.redac.carrier import Carrier
        from pybrid.redac.cluster import Cluster
        from pybrid.redac.blocks import UBlock, CBlock, IBlock
        from pybrid.redac.entities import Path

        mac = "AA-BB-CC-DD-EE-FF"
        carrier_path = Path.parse(mac)
        cluster_path = carrier_path / "0"
        cluster = Cluster(
            path=cluster_path,
            ublock=UBlock(path=cluster_path / "U"),
            cblock=CBlock(path=cluster_path / "C"),
            iblock=IBlock(path=cluster_path / "I"),
            shblock=None,
        )
        carrier = Carrier(
            path=carrier_path,
            clusters=[cluster],
            tblock=None,
        )
        new_computer = LUCIStack(entities=[carrier])

        # Mock the grandparent's set_computer to capture the argument
        captured_args = []

        async def mock_set_computer(computer_arg):
            """Capture the argument passed to REDAC.set_computer."""
            captured_args.append(computer_arg)

        with patch.object(
            REDAC.__mro__[0].__bases__[0] if hasattr(REDAC, '__mro__') else REDAC,
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

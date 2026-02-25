# Copyright (c) 2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
Unit tests for LUCIDACController.

These tests verify that:
- set_computer() passes the argument to the parent (not self.computer).
- validate_sample_counts() applies the configured GapFillMode correctly.
"""

import pytest
from unittest.mock import AsyncMock, patch

from pybrid.lucidac.controller import Controller as LUCIStackController
from pybrid.processing.gap_fill import GapFillMode
from pybrid.redac.computer import REDAC
from pybrid.redac.entities import Path
from pybrid.redac.run import Run

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


def _make_run(**channel_data: list[float]) -> Run:
    """Build a Run with pre-populated data channels.

    Each keyword argument maps a channel name (str) to a list of samples.
    Uses ``defaultdict(list)`` to match the real ``Run.data`` type.

    :param channel_data: Channel name → sample list.
    :returns: A Run instance with the given data.
    """
    run = Run()
    for key, values in channel_data.items():
        path = Path.parse(key)
        run.data[path] = list(values)
    return run


class TestValidateSampleCounts:
    """Tests for Controller.validate_sample_counts() with GapFillMode."""

    def test_gap_fill_mode_none_raises(self):
        """NONE mode raises RuntimeError on sample count mismatch."""
        ctrl = LUCIStackController(gap_fill_mode=GapFillMode.NONE)
        run = _make_run(
            **{"AA-BB-CC-DD-EE-FF/0/ADC0": [1.0, 2.0, 3.0],
               "11-22-33-44-55-66/0/ADC0": [1.0, 2.0]}
        )
        with pytest.raises(RuntimeError, match="Sample count mismatch"):
            ctrl.validate_sample_counts(run)

    def test_gap_fill_mode_zero_pads_with_zeros(self):
        """ZERO mode pads shorter channels with 0.0."""
        ctrl = LUCIStackController(gap_fill_mode=GapFillMode.ZERO)
        run = _make_run(
            **{"AA-BB-CC-DD-EE-FF/0/ADC0": [1.0, 2.0, 3.0],
               "11-22-33-44-55-66/0/ADC0": [4.0]}
        )
        ctrl.validate_sample_counts(run)

        path_short = Path.parse("11-22-33-44-55-66/0/ADC0")
        values = run.data[path_short]
        assert values == [4.0, 0.0, 0.0], (
            f"ZERO mode padding should be 0.0, got {values}"
        )

    def test_gap_fill_mode_repeat_pads_with_last_value(self):
        """REPEAT mode pads shorter channels with their last value."""
        ctrl = LUCIStackController(gap_fill_mode=GapFillMode.REPEAT)
        run = _make_run(
            **{"AA-BB-CC-DD-EE-FF/0/ADC0": [1.0, 2.0, 3.0],
               "11-22-33-44-55-66/0/ADC0": [7.5]}
        )
        ctrl.validate_sample_counts(run)

        path_short = Path.parse("11-22-33-44-55-66/0/ADC0")
        values = run.data[path_short]
        assert values == [7.5, 7.5, 7.5], (
            f"REPEAT mode should pad with last value (7.5), got {values}"
        )

    def test_gap_fill_mode_interpolate_falls_back_to_repeat(self):
        """INTERPOLATE mode falls back to REPEAT for tail-loss gaps (no next value)."""
        ctrl = LUCIStackController(gap_fill_mode=GapFillMode.INTERPOLATE)
        run = _make_run(
            **{"AA-BB-CC-DD-EE-FF/0/ADC0": [1.0, 2.0, 3.0, 4.0, 5.0],
               "11-22-33-44-55-66/0/ADC0": [10.0, 20.0, 30.0]}
        )
        ctrl.validate_sample_counts(run)

        path_short = Path.parse("11-22-33-44-55-66/0/ADC0")
        values = run.data[path_short]
        assert len(values) == 5
        # Tail loss: last two values should repeat 30.0
        assert values == [10.0, 20.0, 30.0, 30.0, 30.0], (
            f"INTERPOLATE should fall back to REPEAT for tail loss, got {values}"
        )

    def test_gap_fill_mode_multi_carrier(self):
        """Multiple carriers with different gaps all get padded correctly."""
        ctrl = LUCIStackController(gap_fill_mode=GapFillMode.REPEAT)
        run = _make_run(
            **{"AA-BB-CC-DD-EE-FF/0/ADC0": [float(i) for i in range(10)],
               "AA-BB-CC-DD-EE-FF/0/ADC1": [float(i) for i in range(10)],
               "11-22-33-44-55-66/0/ADC0": [float(i) for i in range(7)],
               "11-22-33-44-55-66/0/ADC1": [float(i) for i in range(7)]}
        )
        ctrl.validate_sample_counts(run)

        for key, values in run.data.items():
            assert len(values) == 10, (
                f"Channel {key} should have 10 samples after padding, got {len(values)}"
            )

        # Verify repeat padding uses last value (6.0) for the short channels
        path_short = Path.parse("11-22-33-44-55-66/0/ADC0")
        values = run.data[path_short]
        assert values[7:] == [6.0, 6.0, 6.0], (
            f"REPEAT should pad with last value (6.0), got tail: {values[7:]}"
        )

    def test_gap_fill_mode_equal_counts_noop(self):
        """When all channels have equal sample counts, no padding occurs."""
        ctrl = LUCIStackController(gap_fill_mode=GapFillMode.NONE)
        run = _make_run(
            **{"AA-BB-CC-DD-EE-FF/0/ADC0": [1.0, 2.0, 3.0],
               "AA-BB-CC-DD-EE-FF/0/ADC1": [4.0, 5.0, 6.0]}
        )
        ctrl.validate_sample_counts(run)  # should not raise even in NONE mode

    def test_gap_fill_mode_empty_data_noop(self):
        """Empty run.data is a no-op regardless of mode."""
        for mode in [GapFillMode.NONE, GapFillMode.ZERO,
                     GapFillMode.REPEAT, GapFillMode.INTERPOLATE]:
            ctrl = LUCIStackController(gap_fill_mode=mode)
            run = Run()
            ctrl.validate_sample_counts(run)  # should not raise

    def test_gap_fill_mode_logs_warning(self, caplog):
        """Padding modes log a warning when padding occurs."""
        ctrl = LUCIStackController(gap_fill_mode=GapFillMode.ZERO)
        run = _make_run(
            **{"AA-BB-CC-DD-EE-FF/0/ADC0": [1.0, 2.0, 3.0],
               "11-22-33-44-55-66/0/ADC0": [1.0]}
        )
        with caplog.at_level("WARNING", logger="pybrid.lucidac.controller"):
            ctrl.validate_sample_counts(run)

        assert any("padded" in msg for msg in caplog.messages), (
            f"Expected warning about padding, got: {caplog.messages}"
        )

    @pytest.mark.parametrize("strict_value,expected_mode", [
        (True, GapFillMode.NONE),
        (False, GapFillMode.ZERO),
    ])
    def test_deprecated_strict_maps_to_gap_fill_mode(self, strict_value, expected_mode):
        """Deprecated strict= keyword maps to the corresponding GapFillMode."""
        with pytest.warns(DeprecationWarning, match="strict"):
            ctrl = LUCIStackController(strict=strict_value)
        assert ctrl.gap_fill_mode == expected_mode

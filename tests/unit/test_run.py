# Copyright (c) 2022-2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
Unit tests for Run-related classes in pybrid.redac.run module.

Tests cover:
- RunState enum and its methods
- RunConfig dataclass
- RunFlags dataclass
- Run class
"""

from collections import defaultdict
from uuid import UUID

import pytest

import pybrid.base.proto.main_pb2 as pb
from pybrid.redac.run import Run, RunConfig, RunFlags, RunState
from pybrid.redac.entities import Path


class TestRunState:
    """Tests for RunState enum."""

    def test_default(self):
        """RunState.default() should return NEW state."""
        assert RunState.default() == RunState.NEW

    @pytest.mark.parametrize(
        "state,expected",
        [
            (RunState.NEW, False),
            (RunState.ERROR, True),
            (RunState.DONE, True),
            (RunState.QUEUED, False),
            (RunState.TAKE_OFF, False),
            (RunState.IC, False),
            (RunState.OP, False),
            (RunState.OP_END, False),
            (RunState.TMP_HALT, False),
        ],
    )
    def test_is_done(self, state, expected):
        """is_done() should return True only for DONE and ERROR states."""
        assert state.is_done() == expected

    def test_possibly_sampled_states(self):
        """get_possibly_sampled_states() should return IC, OP, OP_END."""
        sampled_states = RunState.get_possibly_sampled_states()
        assert sampled_states == (RunState.IC, RunState.OP, RunState.OP_END)

    @pytest.mark.parametrize(
        "pb_state,expected",
        [
            (pb.RunState.NEW, RunState.NEW),
            (pb.RunState.ERROR, RunState.ERROR),
            (pb.RunState.DONE, RunState.DONE),
            (pb.RunState.QUEUED, RunState.QUEUED),
            (pb.RunState.TAKE_OFF, RunState.TAKE_OFF),
            (pb.RunState.IC, RunState.IC),
            (pb.RunState.OP, RunState.OP),
            (pb.RunState.OP_END, RunState.OP_END),
            (pb.RunState.TMP_HALT, RunState.TMP_HALT),
        ],
    )
    def test_from_pb(self, pb_state, expected):
        """from_pb() should correctly convert protobuf RunState to RunState enum."""
        assert RunState.from_pb(pb_state) == expected

    def test_from_pb_unknown_returns_error(self):
        """from_pb() with an unknown/invalid value should return ERROR state."""
        # Use an arbitrary integer that doesn't correspond to any known state
        # The implementation returns ERROR for any unrecognized state
        unknown_value = 9999
        assert RunState.from_pb(unknown_value) == RunState.ERROR

class TestRun:
    """Tests for Run dataclass."""

    def test_default_state(self):
        """Run should have NEW state by default."""
        run = Run()
        assert run.state == RunState.NEW

    def test_uuid_generation(self):
        """Run should generate a UUID by default."""
        run = Run()
        assert isinstance(run.id_, UUID)

    def test_unique_uuids(self):
        """Each new Run should have a unique UUID."""
        run1 = Run()
        run2 = Run()
        run3 = Run()

        assert run1.id_ != run2.id_
        assert run2.id_ != run3.id_
        assert run1.id_ != run3.id_

    def test_data_is_defaultdict(self):
        """Run.data should be a defaultdict(list)."""
        run = Run()

        assert isinstance(run.data, defaultdict)
        # Verify it works like a defaultdict with list factory
        run.data["test_key"].append(1.0)
        run.data["test_key"].append(2.0)
        assert run.data["test_key"] == [1.0, 2.0]
        # Accessing a non-existent key should return empty list
        assert run.data["nonexistent"] == []

    def test_persistent_attributes(self):
        """Run.get_persistent_attributes() should include config plus redac-specific attrs."""
        persistent = Run.get_persistent_attributes()

        # Should include "config" from base class
        assert "config" in persistent
        # Should include redac-specific attributes
        assert "daq" in persistent
        assert "sync" in persistent
        assert "partition" in persistent

    def test_custom_state(self):
        """Run should accept custom state on creation."""
        run = Run(state=RunState.QUEUED)
        assert run.state == RunState.QUEUED

    def test_related_to(self):
        """Run should support related_to linking."""
        run1 = Run()
        run2 = Run(related_to=run1.id_)

        assert run2.related_to == run1.id_

    def test_final_values_dict(self):
        """Run.final_values should be an empty dict by default."""
        run = Run()
        assert run.final_values == {}
        assert isinstance(run.final_values, dict)

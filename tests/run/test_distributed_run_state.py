# Copyright (c) 2022-2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
Distributed Run State Tests
===========================

Tests for the DistributedRunState class which tracks run state
across multiple devices/paths in a distributed analog computer setup.

Test Categories
---------------
1. Initialization - Creating DistributedRunState with/without paths
2. Path Management - Adding paths and duplicate detection
3. State Tracking - Tracking state changes
4. State Waiting - wait_all functionality and timeouts
5. Error Handling - ERROR state propagation
"""

import asyncio
import pytest

from pybrid.redac import Path, RunState, Run, RunError
from pybrid.redac.controller import DistributedRunState


class TestDistributedRunStateInit:
    """Tests for DistributedRunState initialization."""

    async def test_initialization_with_paths(self):
        run = Run()
        path_one = Path.parse("00-00-00-00-00-00")
        path_two = Path.parse("00-00-00-00-00-01")

        run_state = DistributedRunState(run, paths=[path_one, path_two])

        involved_paths = list(run_state.get_involved_paths())
        assert len(involved_paths) == 2
        assert path_one in involved_paths
        assert path_two in involved_paths


class TestDistributedRunStatePathManagement:
    """Tests for path addition and management."""

    async def test_add_paths_duplicate_raises(self):
        run = Run()
        run_state = DistributedRunState(run)
        path = Path.parse("00-00-00-00-00-00")

        run_state.add_paths(path)

        with pytest.raises(ValueError, match="already being tracked"):
            run_state.add_paths(path)


class TestDistributedRunStateTracking:
    """Tests for state change tracking."""

    async def test_track_state_change(self):
        run = Run()
        run_state = DistributedRunState(run)
        path = Path.parse("00-00-00-00-00-00")
        run_state.add_paths(path)

        # Initially, wait_all should timeout since no state is reached
        with pytest.raises(asyncio.TimeoutError):
            async with asyncio.timeout(0.05):
                await run_state.wait_all(RunState.QUEUED)

        # Track the path transitioning to QUEUED
        run_state.track(path, RunState.QUEUED)

        # Now wait_all should complete immediately
        async with asyncio.timeout(0.1):
            await run_state.wait_all(RunState.QUEUED)

    async def test_full_state_cycle(self):
        run = Run()
        run_state = DistributedRunState(run)
        path = Path.parse("00-00-00-00-00-00")
        run_state.add_paths(path)

        state_sequence = [
            RunState.QUEUED,
            RunState.TAKE_OFF,
            RunState.IC,
            RunState.OP,
            RunState.OP_END,
            RunState.DONE,
        ]

        for state in state_sequence:
            run_state.track(path, state)
            async with asyncio.timeout(0.1):
                await run_state.wait_all(state)

        # Verify final state is DONE by calling wait_all again (should complete immediately)
        async with asyncio.timeout(0.1):
            await run_state.wait_all(RunState.DONE)


class TestDistributedRunStateWaiting:
    """Tests for wait_all functionality."""

    async def test_wait_all_timeout(self):
        run = Run()
        run_state = DistributedRunState(run)
        path_one = Path.parse("00-00-00-00-00-00")
        path_two = Path.parse("00-00-00-00-00-01")
        run_state.add_paths(path_one, path_two)

        # Only one path reaches the state
        run_state.track(path_one, RunState.QUEUED)

        # wait_all should timeout since path_two hasn't reached QUEUED
        with pytest.raises(asyncio.TimeoutError):
            async with asyncio.timeout(0.1):
                await run_state.wait_all(RunState.QUEUED)


class TestDistributedRunStateErrors:
    """Tests for error state handling."""

    async def test_distributed_run_state_error(self):
        run = Run()
        run_state: DistributedRunState = DistributedRunState(run)
        path_one = Path.parse("00-00-00-00-00-00")
        path_two = Path.parse("00-00-00-00-00-01")
        run_state.add_paths(path_one, path_two)

        run_state.track(path_one, RunState.QUEUED)
        run_state.track(path_two, RunState.QUEUED)
        async with asyncio.timeout(0.1):
            await run_state.wait_all(RunState.QUEUED)
        async with asyncio.timeout(0.1):
            await run_state.wait_all(RunState.QUEUED)

        run_state.track(path_one, RunState.TAKE_OFF)
        with pytest.raises(asyncio.TimeoutError):
            async with asyncio.timeout(0.1):
                await run_state.wait_all(RunState.TAKE_OFF)

        run_state.track(path_one, RunState.DONE)
        run_state.track(path_two, RunState.ERROR)
        with pytest.raises(RunError):
            await run_state.wait_all(RunState.DONE)

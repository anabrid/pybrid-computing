# Copyright (c) 2022-2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
Test helper utilities for pybrid test suite.

This module provides common patterns for test execution and state verification.
Use these utilities alongside conftest.py fixtures.

Boundary:
- conftest.py: pytest fixtures (decorated with @pytest.fixture)
- helpers.py: non-fixture utilities (pure functions, constants)

Categories:
1. Timeout Constants - Standardized timeout values
2. Run Execution - Standard patterns for executing runs
3. State Verification - Waiting for and verifying run states
4. Timeout Calculation - Compute timeouts from op_time
"""

import asyncio
from uuid import uuid4
from typing import TYPE_CHECKING

from pybrid.redac.run import Run, RunConfig, RunState, DAQConfig
from pybrid.redac.controller import DistributedRunState

if TYPE_CHECKING:
    from pybrid.redac.controller import Controller


# =============================================================================
# Timeout Constants
# =============================================================================

TIMEOUT_SHORT = 5.0
TIMEOUT_MEDIUM = 15.0
TIMEOUT_LONG = 30.0
TIMEOUT_EXTENDED = 60.0


# =============================================================================
# Run Execution Helpers
# =============================================================================

async def execute_run(
    ctrl: "Controller",
    ic_time_ns: int = 10_000,
    op_time_ns: int = 100_000,
    daq: DAQConfig | None = None,
    timeout: float = TIMEOUT_MEDIUM,
) -> tuple[DistributedRunState, Run]:
    """
    Execute a standard test run with the given parameters.

    Args:
        ctrl: The connected Controller instance.
        ic_time_ns: Initial condition time in nanoseconds (default: 10us).
        op_time_ns: Operation time in nanoseconds (default: 100us).
        daq: Optional DAQ configuration for sampling.
        timeout: Maximum wait time for run completion.

    Returns:
        Tuple of (DistributedRunState, Run) after completion.

    Raises:
        asyncio.TimeoutError: If run doesn't complete within timeout.
    """
    run = Run(
        id_=uuid4(),
        config=RunConfig(ic_time=ic_time_ns, op_time=op_time_ns),
        daq=daq,
    )
    run_state = await ctrl.start_run(run)
    async with asyncio.timeout(timeout):
        await run_state.wait_all(RunState.DONE)
    return run_state, run


async def execute_run_with_config(
    ctrl: "Controller",
    config_bundle,
    ic_time_ns: int = 100_000,
    op_time_ns: int = 10_000_000,
    daq: DAQConfig | None = None,
    timeout: float = TIMEOUT_LONG,
) -> tuple[DistributedRunState, Run]:
    """
    Execute a run after sending a configuration bundle.

    Args:
        ctrl: The connected Controller instance.
        config_bundle: Configuration to send before the run.
        ic_time_ns: Initial condition time in nanoseconds.
        op_time_ns: Operation time in nanoseconds.
        daq: Optional DAQ configuration.
        timeout: Maximum wait time.

    Returns:
        Tuple of (DistributedRunState, Run) after completion.
    """
    await ctrl.set_config_bundle(config_bundle)
    return await execute_run(ctrl, ic_time_ns, op_time_ns, daq, timeout)


# =============================================================================
# State Verification Helpers
# =============================================================================

async def wait_for_state(
    run_state: DistributedRunState,
    target_state: RunState,
    timeout: float = TIMEOUT_MEDIUM,
) -> None:
    """
    Wait for all paths in a run state to reach the target state.

    Args:
        run_state: The DistributedRunState to monitor.
        target_state: The RunState to wait for.
        timeout: Maximum wait time.

    Raises:
        asyncio.TimeoutError: If not all paths reach target state.
        RunError: If any path enters ERROR state.
    """
    async with asyncio.timeout(timeout):
        await run_state.wait_all(target_state)


def format_run_status(run_state: DistributedRunState, target_state: RunState) -> str:
    """
    Format current run status for error messages.

    Args:
        run_state: The DistributedRunState to format.
        target_state: The target state being waited for.

    Returns:
        Human-readable status string.
    """
    reached, not_reached = run_state.status(target_state)
    total = len(reached) + len(not_reached)
    return f"{len(reached)}/{total} paths reached {target_state.name}"


# =============================================================================
# Timeout Calculation
# =============================================================================

def calculate_run_timeout(op_time_ns: int, buffer_seconds: float = 5.0) -> float:
    """
    Calculate appropriate timeout for a run based on op_time.

    Args:
        op_time_ns: Operation time in nanoseconds.
        buffer_seconds: Additional buffer time.

    Returns:
        Timeout value in seconds.
    """
    return (op_time_ns / 1e9) + buffer_seconds

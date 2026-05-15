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
from typing import TYPE_CHECKING
from uuid import uuid4

from pybrid.redac.controller import DistributedRunState
from pybrid.redac.run import DAQConfig, Run, RunConfig, RunState

if TYPE_CHECKING:
    from pybrid.redac.controller import Controller


TIMEOUT_SHORT = 5.0
TIMEOUT_MEDIUM = 15.0
TIMEOUT_LONG = 30.0
TIMEOUT_EXTENDED = 60.0


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

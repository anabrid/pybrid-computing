# Copyright (c) 2022-2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import asyncio
import pytest

from pybrid.redac import Path, RunState, Run, RunError
from pybrid.redac.controller import DistributedRunState


async def test_distributed_run_state_error():
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


if __name__ == "__main__":
    asyncio.run(test_distributed_run_state_error())

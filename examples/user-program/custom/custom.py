# Example of a UserProgram with completely custom process flow

import asyncio

from pyanabrid.base.hybrid.programs.base import BaseProgram
from pyanabrid.redac import REDAC, Run, RunConfig, DAQConfig


class UserProgram(BaseProgram):
    # Type hint, just for IDE completion
    computer: REDAC

    async def sync_configuration(self):
        return await self.controller.set_computer(self.computer)

    async def start(self):
        # Reference to first cluster on first carrier board
        cluster = self.computer.carriers[0].clusters[0]

        # Configure harmonic oscillator
        # Or do something else
        cluster.route(8, 0, -1.0, 9)
        cluster.route(9, 1, 1.0, 8)
        # Configure initial value
        cluster.m0block.elements[0].ic = 0.42

        # Set configuration
        await self.sync_configuration()

        # Wait some time
        await asyncio.sleep(2)

        # Do something else
        # cluster.m0block.elements[0].ic = ...
        # ...
        # await self.sync_configuration()
        # ...

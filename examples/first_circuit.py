import asyncio

import numpy as np
from matplotlib import pyplot as plt

from pybrid.lucidac.controller import Controller
from pybrid.redac import DAQConfig, RunConfig


async def main():

    async with Controller() as controller:

        # connect to LUCIDAC
        await controller.add_device("192.168.1.2", 5732)

        # retrieve the entity object model for the LUCIDAC (i.e. "cluster")
        computer = controller.computer
        carrier = computer.carriers[0]
        cluster = carrier.clusters[0]

        ###
        # CONFIGURATION
        ###

        # set initial conditions for integrators (integrators 0, 1)
        cluster.m0block.elements[0].ic = 0.42
        cluster.m0block.elements[1].ic = 0  # 0 by default

        # connnect integrators through U, C, I blocks
        cluster.ublock.outputs[0] = 0
        cluster.cblock.elements[0] = -1.0
        cluster.iblock.outputs[1] = [0]

        cluster.ublock.outputs[1] = 1
        cluster.cblock.elements[1] = 1.0
        cluster.iblock.outputs[0] = [1]

        # ALTERNATIVE: connect via convenient router() functionality
        # cluster.route(0, 0, -1.0, 1)
        # cluster.route(1, 1, 1.0, 0)

        # capture of both integrators' output signals
        computer.daq.capture(cluster.m0block.elements[0], cluster.m0block.elements[1])

        ###
        # EXECUTION
        ###

        # determine how many samples are drawn per channel and how long we
        # are integrating (= OP time, in ns)
        run_config = RunConfig(op_time=2_560_000)
        daq_config = DAQConfig(sample_rate=100_000)

        # create a session (used to concatenate multiple commands and let the
        # runtime handle their processing
        session = controller.create_session()
        runs = await (
            session.set_config(computer)  # seriazlize and send configuration
            .calibrate(gain=True, offset=True)
            .run(run_config, daq_config)
            .execute()  # execute all of the former commands
        )

        # only one circuit executed - pick first run object; run.data then
        # contains one list of samples per captured element
        run = runs[0]

        # Plot data.
        for channel in run.data:
            if channel is not None:
                plt.plot(np.array(channel).flatten())
        plt.ylabel("Amplitude x")
        plt.xlabel("'Time' t")
        plt.show()


asyncio.run(main())

import asyncio
import logging
from ipaddress import ip_network

import numpy as np
from matplotlib import pyplot as plt

from pybrid.base.utils.logging import set_pybrid_logging_level
from pybrid.redac import Controller, DAQConfig, RunConfig
from pybrid.redac.detect import detect_in_network

logging.basicConfig()
set_pybrid_logging_level(logging.DEBUG)


async def main():
    controller = Controller()

    for host, port, name in await detect_in_network(ip_network("0.0.0.0/0")):
        await controller.add_device(host, port)

    async with controller:
        await controller.reset()

        computer = controller.computer
        cluster = computer.carriers[0].clusters[0]

        # Configure harmonic oscillator: dx0/dt = -x1, dx1/dt = x0
        cluster.route(0, 0, -1.0, 1)
        cluster.route(1, 1, 1.0, 0)
        cluster.m0block.elements[0].ic = 0.42

        # Capture both integrator outputs
        computer.daq.capture(cluster.m0block.elements[0], cluster.m0block.elements[1])

        # Execute via session
        run_config = RunConfig(op_time=2_560_000)
        daq_config = DAQConfig(num_channels=2, sample_rate=100_000)

        session = controller.create_session()
        runs = await session.set_config(computer).run(run_config, daq=daq_config).execute()
        run = runs[0]

    # Plot data.
    for channel in run.data:
        if channel is not None:
            plt.plot(np.array(channel).flatten())
    plt.ylabel("Amplitude x")
    plt.xlabel("'Time' t")
    plt.show()


asyncio.run(main())

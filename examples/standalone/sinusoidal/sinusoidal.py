import asyncio
import logging
from ipaddress import ip_network

import numpy as np
from matplotlib import pyplot as plt
from pybrid.base.utils.logging import set_pybrid_logging_level
from pybrid.redac import Controller, DAQConfig, RunConfig
from pybrid.redac.detect import detect_in_network

# For development purposes, set all logging to DEBUG
logging.basicConfig()
set_pybrid_logging_level(logging.DEBUG)

async def main():
    # Create a controller, which uses the protocol to execute commands.
    controller = Controller(standalone=True)
    # Reference for run.
    run = None

    for (host, port, name) in await detect_in_network(ip_network("0.0.0.0/0")):
        await controller.add_device(host, port)

    # The controller needs to run through an initialization and de-initialization procedure.
    # To ensure both, it can be used as an async context manager.
    async with controller:
        # First things first, reset the analog computer, so we have a clean slate.
        await controller.reset()

        # The controller automatically retrieves the available hardware of the analog computer.
        computer = controller.computer
        # Configure harmonic oscillator on the first cluster of the first carrier.
        cluster = computer.carriers[0].clusters[0]

        # Configure harmonic oscillator
        cluster.route(0, 0, -1.0, 1)
        cluster.route(1, 1, 1.0, 0)
        # Configure initial value
        cluster.m0block.elements[0].ic = 0.42

        computer.daq.capture(cluster.m0block.elements[0], cluster.m0block.elements[1])

        # Upload the changed configuration to the analog computer
        await controller.set_computer(computer)

        # Create a run and configure it.
        run_config = RunConfig(op_time=2_560_000)
        daq_config = DAQConfig(num_channels=2, sample_rate=100_000)
        run_class = controller.get_run_implementation()
        run = run_class(config=run_config, daq=daq_config)

        # Start a run and wait for its result.
        # Alternatively, you can use non-blocking functions and do other (hybrid) work in parallel.
        await controller.start_and_await_run(run)

    # Since we only have one run (calculation), we don't need the controller anymore.
    # By exiting the with statement, protocol communication is stopped.

    # Plot data.
    for channel in run.data.values():
        plt.plot(np.array(channel).flatten())
    plt.ylabel("Amplitude x")
    plt.xlabel("'Time' t")
    plt.show()


asyncio.run(main())

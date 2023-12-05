import asyncio
import logging

from matplotlib import pyplot as plt
from pyanabrid.base.utils.logging import set_pyanabrid_logging_level
from pyanabrid.base.transport.network import TCPTransport
from pyanabrid.redac import Protocol, Controller, DAQConfig, RunConfig

# For development purposes, set all logging to DEBUG
logging.basicConfig()
set_pyanabrid_logging_level(logging.DEBUG)

# Network information of REDAC
REDAC_HOST = 'b.dev.redac.lan'
REDAC_PORT = 5732


async def main():
    # Create a transport, which handles the underlying network connection.
    transport = await TCPTransport.create(REDAC_HOST, REDAC_PORT)
    # Create a protocol, which handles the message communication over the transport.
    protocol = await Protocol.create(transport)
    # Create a controller, which uses the protocol to execute commands.
    controller = await Controller.create(protocol)
    # Reference for run.
    run = None

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
        cluster.route(8, 0, -1.0, 9)
        cluster.route(9, 1, 1.0, 8)
        # Configure initial value
        cluster.m0block.elements[0].ic = 0.42

        # Upload the changed configuration to the analog computer
        await controller.set_computer(computer)

        # Create a run and configure it.
        run_config = RunConfig(op_time=2_560_000)
        daq_config = DAQConfig(num_channels=2, sample_rate=100_000)
        run = await controller.create_run(config=run_config, daq=daq_config)

        # Start a run and wait for its result.
        # Alternatively, you can use non-blocking functions and do other (hybrid) work in parallel.
        await controller.start_and_await_run(run)

    # Since we only have one run (calculation), we don't need the controller anymore.
    # By exiting the with statement, protocol communication is stopped.

    # Plot data.
    t = [t_ / 10 for t_ in run.data.pop("t")]
    for channel in run.data.values():
        plt.plot(t, channel)
    plt.ylabel("Amplitude x")
    plt.xlabel("'Time' t")
    plt.show()

asyncio.run(main())

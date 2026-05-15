# Copyright (c) 2022-2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later
"""
Sine function example using a harmonic oscillator on a single mREDAC.

This serves as a test case for the front panel I/O on an mREDAC.
Plug in:
- an oscilloscope to ports 0, 1, 3
- a function generator to port 2

And set the trigger to port 3 (on falling flank). If successfull, you should see
two generated harmonic oscilllators on inputs 0, 1 on the oscilloscope. The ADCs
show the same generated oscillators plus the signal generator's signal.
"""

import asyncio

import numpy as np
from matplotlib import pyplot as plt

from pybrid.redac import Controller, DAQConfig, RunConfig
from pybrid.redac.carrier import ADCChannel, FrontPanelIOMode


async def main():
    """Create and run a harmonic oscillator on a mREDAC via IP."""

    # Configure logging for debugging (optional - comment out for quiet operation)
    # logging.basicConfig()
    # set_pybrid_logging_level(logging.DEBUG)

    # Create a controller for communication with the mREDAC
    controller = Controller()

    # Connect to the mREDAC at the specified IP address
    # The default REDAC port is 5732
    mredac_ip = "192.168.100.131"
    mredac_port = 5732

    print(f"Connecting to mREDAC at {mredac_ip}:{mredac_port}...")
    await controller.add_device(mredac_ip, mredac_port)

    # Use the controller as an async context manager for proper initialization
    async with controller:
        # Reset the analog computer to a clean state
        print("Resetting mREDAC...")
        await controller.reset()

        # Get the computer structure (automatically retrieved during initialization)
        computer = controller.computer
        carrier = computer.carriers[0]
        cluster = carrier.clusters[0]

        # define an harmonic oscillator
        freq_hz = 100.0  # Desired frequency in Hz
        omega = 2 * np.pi * freq_hz / 10000  # Scaled angular frequency for circuit

        cluster.route(m_out=1, u_out=29, c_factor=+omega, m_in=0)
        cluster.route(m_out=0, u_out=28, c_factor=-omega, m_in=1)

        cluster.m0block.elements[0].ic = -1
        cluster.m0block.elements[1].ic = 0.0

        cluster.m0block.elements[0].k = 10_000
        cluster.m0block.elements[1].k = 10_000

        # Patch incoming signal through over an ID path
        # Note: MDR block uses ID paths 8 -> 12, 11 -> 13, 13 -> 15, 15 -> 17
        cluster.iblock.outputs[9] = [30]

        # Configure data acquisition to capture both outputs
        carrier.adc_config.extend(
            [ADCChannel(index=0, probe=0), ADCChannel(index=1, probe=1), ADCChannel(index=12, probe=2)]
        )

        # External output
        carrier.front_panel_io = [
            FrontPanelIOMode.ANALOG_OUT,
            FrontPanelIOMode.ANALOG_OUT,
            FrontPanelIOMode.ANALOG_IN,
            FrontPanelIOMode.DIGITAL_OUT,
        ]

        # Configure run parameters
        op_time_us = 100_000_000
        sample_rate = 5_000

        run_config = RunConfig(op_time=op_time_us)
        daq_config = DAQConfig(num_channels=3, sample_rate=sample_rate)

        # execute the session
        session = controller.create_session()
        session.set_config(computer)
        # session.calibrate(gain=False, offset=True)
        session.run(run_config, daq_config)
        await session.execute()

        run = session.runs[0]

    # Controller exits here, connection closed

    # Plot the results
    print("Plotting results...")

    # Create time axis
    num_samples = len(run.data[0])
    time = np.linspace(0, op_time_us / 1_000_000, num_samples)

    # Plot both channels
    plt.figure(figsize=(10, 6))

    for channel_id, channel_data in enumerate(run.data):
        values = np.array(channel_data).flatten()
        plt.plot(time * 1000, values, label=f"Channel {channel_id}")

    plt.xlabel("Time / ms")
    plt.ylabel("Amplitude")
    plt.title(f"Harmonic Oscillator (omega = {omega} rad/s)")
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.show()

    print("Done!")


if __name__ == "__main__":
    asyncio.run(main())

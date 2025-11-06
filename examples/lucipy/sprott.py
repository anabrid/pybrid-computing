# Copyright (c) 2022-2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later
"""
Sprott SQm System

This example implements the Sprott SQm system on the LUCIDAC.

Reference: Analog Paradigm Application Note 31
https://analogparadigm.com/downloads/alpaca_31.pdf
"""

from pybrid.lucidac.lucipy import Circuit, LUCIDAC
import matplotlib.pyplot as plt
import numpy as np


###
# Create a Sprott attractor circuit in lucipy-syntax
###

sprott  = Circuit()                     # Create a circuit

scale = 0.7                             # Scaling factor

mx      = sprott.int(ic = .1)           # Integrators with initial condition
my      = sprott.int()
mz      = sprott.int()
mxy     = sprott.mul()                  # Multipliers for nonlinear terms
yz      = sprott.mul()
const   = sprott.const()                # Constant source

sprott.connect(yz, mx, weight = 10 * scale)         # x' = yz

sprott.connect(mx, my, weight = -1 * scale)         # y' = x - y
sprott.connect(my, my, weight = +1 * scale)
sprott.connect(const, mz, weight = 0.1 * scale)     # z' = 1 - xy (scaled!)

sprott.connect(mxy, mz, weight = 10 * scale)

sprott.connect(mx, mxy.a, weight = +1 * scale)      # Compute -xy
sprott.connect(my, mxy.b, weight = -1 * scale)

sprott.connect(my, yz.a)                            # Compute yz
sprott.connect(mz, yz.b)

sprott.measure(mx, adc_channel=0)                   # Connect integrators to ADC
sprott.measure(my, adc_channel=1)                   # to sample data
sprott.measure(mz, adc_channel=2)

###
# Auto-detect LUCIDAC-device (empty constructor) or:
# - set environment variable LUCIDAC_ENDPOINT to a connection string
# - pass the connection string directly
#
# where the connection string is `tcp://<LUCIDAC IP or hostname>:5732`.
###
luci    = LUCIDAC()

luci.set_circuit(sprott)                # Assign circuit

###
# Settings for sampling and circuit execution
###
op_secs     = .1                        # Duration of OP cycle in seconds
sample_rate = 100_000                   # Samples per second (max: 150_000 for each channel)

luci.set_daq(num_channels=3, sample_rate=sample_rate)
luci.set_run(ic_time = 1_000, op_time=int(op_secs * 1_000_000_000))

###
# Run circuit and start sampling
###
run = luci.run()

###
# Receive sample data and plot
###
samples = list(run.data.values())

ax = plt.figure().add_subplot(projection='3d')
ax.plot(*np.array(samples), ls="-", marker="", markersize=1.5)
ax.set_xlabel("X")
ax.set_ylabel("Y")
ax.set_zlabel("Z")
plt.show()
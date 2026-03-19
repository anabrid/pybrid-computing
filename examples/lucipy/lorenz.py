# Copyright (c) 2022-2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later
"""
Lorenz Attractor

This example implements the Lorenz attractor on the LUCIDAC.

Reference: Analog Paradigm Application Note 2
https://analogparadigm.com/downloads/alpaca_2.pdf
"""

from pybrid.lucipy import Circuit, LUCIDAC
import matplotlib.pyplot as plt
import numpy as np


###
# Create a simple circuit in lucipy-syntax
###

###
# Auto-detect LUCIDAC-device (empty constructor) or:
# - set environment variable LUCIDAC_ENDPOINT to a connection string
# - pass the connection string directly
#
# where the connection string is `tcp://<LUCIDAC IP or hostname>:5732`.
###
luci    = LUCIDAC()

l   = luci.create_circuit()             # Create a circuit

a   = 1.0
b   = 2.8
c   = 2.666 / 10

mx  = l.int()                           # Integrators with initial condition
my  = l.int()
mz  = l.int(ic = .3)
xz  = l.mul()
xy  = l.mul()

l.connect(mx, xz.a)                     # Product -x * -z = xz
l.connect(mz, xz.b, weight = 2)

l.connect(mx, xy.a)                     # Product -x * -y = xy
l.connect(my, xy.b)

l.connect(my, mx, weight = -a)
l.connect(mx, mx, weight = +a)

l.connect(mx, my, weight = -b)
l.connect(xz, my, weight = -5)
l.connect(my, my, weight = .1)

l.connect(xy, mz, weight = 2.5)
l.connect(mz, mz, weight = c)

l.probe(mx, adc_channel = 0)            # Connect multiplier/integrator to ADC
                                        # to sample data
l.probe(my, adc_channel = 1)
l.probe(mz, adc_channel = 2)

# Analog output: uncomment to output the x, y, z signals on Analog Outputs
# 0, 1, 2
# l.probe(mx, front_port=0)
# l.probe(my, front_port=1)
# l.probe(mz, front_port=2)

###
# Settings for smapling and cirucit execution
###
op_secs     = .1                        # duration of OP cycle in seconds
sample_rate = 100_000                   # samples per second (max: 150_000 for each channel)

luci.set_daq(num_channels=3, sample_rate=sample_rate)
luci.set_run(ic_time = 1_000, op_time=int(op_secs * 1_000_000_000))

###
# Run circuit and start sampling
###
run = luci.run()

###
# Receive sample data and plot
###
ax = plt.figure().add_subplot(projection='3d')
ax.plot(*np.array(run.data), ls="-", marker="+", markersize=1.5)
ax.set_xlabel("X")
ax.set_ylabel("Y")
ax.set_zlabel("Z")
plt.show()
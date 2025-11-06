# Copyright (c) 2022-2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later
"""
Sprott Chaotic System

This example implements the Sprott chaotic system on the LUCIDAC.

Reference: Analog Paradigm Application Note 43
https://analogparadigm.com/downloads/alpaca_43.pdf
"""

from pybrid.lucidac.lucipy import Circuit, LUCIDAC
import matplotlib.pyplot as plt
import numpy as np


###
# Create a Sprott attractor (variant 2) circuit in lucipy-syntax
###

sprott  = Circuit()                     # Create a circuit

a = 1.66                                # System parameter

x = sprott.int(ic = 0.2)                # Integrators with initial conditions
y = sprott.int()
z = sprott.int()
y2 = sprott.mul()                       # Multiplier for nonlinear term

sprott.connect( y, x, weight = +0.5)

sprott.connect( z, y)

sprott.connect( z, z, weight = a)
sprott.connect( x, z, weight = +2.)
sprott.connect(y2, z, weight = +5.)

sprott.connect(y, y, weight = +0.1)

sprott.connect( y, y2.a)                # Compute y^2
sprott.connect( y, y2.b)

sprott.measure(x, adc_channel=0)        # Connect integrators to ADC
sprott.measure(y, adc_channel=1)        # to sample data
sprott.measure(z, adc_channel=2)

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
ax.plot(*np.array(samples), ls="-", marker=".", markersize=1.5)
ax.set_xlabel("X")
ax.set_ylabel("Y")
ax.set_zlabel("Z")
plt.show()
# Copyright (c) 2022-2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

from pybrid.lucidac.lucipy import Circuit, LUCIDAC
import matplotlib.pyplot as plt
import numpy as np

###
# Create a Roessler attractor circuit in lucipy-syntax
###

r   = Circuit()                         # Create a circuit

x   = r.int(ic = .0066)                 # Integrators with initial conditions
y   = r.int()
z   = r.int()
m   = r.mul()                           # Multiplier for nonlinear term
c   = r.const()                         # Constant source

r.connect(y, x, weight = -0.8)
r.connect(z, x, weight = -2.3)

r.connect(x, y, weight = 1.25)
r.connect(y, y, weight = -0.2)

r.connect(c, z, weight = +0.005)
r.connect(m, z, weight = +5.)           # Multiple connections to amplify
r.connect(m, z, weight = +5.)
r.connect(m, z, weight = +5.)

r.connect(z, m.a, weight = -1)          # Compute nonlinear term
r.connect(x, m.b)
r.connect(c, m.b, weight = -0.3796)

r.measure(x, adc_channel=0)             # Connect integrators to ADC
r.measure(y, adc_channel=1)             # to sample data

###
# Auto-detect LUCIDAC-device (empty constructor) or:
# - set environment variable LUCIDAC_ENDPOINT to a connection string
# - pass the connection string directly
#
# where the connection string is `tcp://<LUCIDAC IP or hostname>:5732`.
###
luci    = LUCIDAC()

luci.set_circuit(r)                     # Assign circuit

###
# Settings for sampling and circuit execution
###
op_secs     = .1                        # Duration of OP cycle in seconds
sample_rate = 100_000                   # Samples per second (max: 150_000 for each channel)

luci.set_daq(num_channels=2, sample_rate=sample_rate)
luci.set_run(ic_time = 1_000, op_time=int(op_secs * 1_000_000_000))

###
# Run circuit and start sampling
###
run = luci.run()

###
# Receive sample data and plot
###
samples = list(run.data.values())

ax = plt.figure().add_subplot()
ax.plot(*np.array(samples), ls="-", marker="+", markersize=1.5)
ax.set_xlabel("X")
ax.set_ylabel("Y")
plt.show()
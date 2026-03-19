# Copyright (c) 2022-2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later
from pybrid.lucipy import Circuit, LUCIDAC, time_series
import matplotlib.pyplot as plt
import numpy as np

###
# Create a Van der Pol oscillator circuit in lucipy-syntax
###

###
# Auto-detect LUCIDAC-device (empty constructor) or:
# - set environment variable LUCIDAC_ENDPOINT to a connection string
# - pass the connection string directly
#
# where the connection string is `tcp://<LUCIDAC IP or hostname>:5732`.
###
luci    = LUCIDAC()

vdp = luci.create_circuit()             # Create a circuit

eta = 4                                 # Nonlinearity parameter

mdy = vdp.int()                         # Integrators
y   = vdp.int(ic = 0.1)
y2  = vdp.mul()                         # Multipliers for nonlinear terms
fb  = vdp.mul()
c   = vdp.const()                       # Constant source

vdp.connect(fb, mdy, weight = -eta)
vdp.connect(y,  mdy, weight = -0.5)

vdp.connect(mdy, y, weight = 2)

vdp.connect(y, y2.a)                    # Compute y^2
vdp.connect(y, y2.b)

vdp.connect(y2,  fb.a, weight = -1)     # Build nonlinear feedback term
vdp.connect(c,   fb.a, weight = 0.25)
vdp.connect(mdy, fb.b)

out0 = vdp.output(0)                    # Allocate output MCX plugs
out1 = vdp.output(1)

vdp.connect(mdy, out0)                  # Connect signals to front panel outputs
vdp.connect(y,   out1)

vdp.probe(mdy)                          # Connect to ADC to sample data
vdp.probe(y)

###
# Settings for sampling and circuit execution
###
op_secs     = 0.01                      # Duration of OP cycle in seconds
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
ax = plt.figure().add_subplot()
ax.plot(*np.array(run.data), ls="-", marker="+", markersize=1.5)
ax.set_xlabel("X")
ax.set_ylabel("Y")
plt.show()
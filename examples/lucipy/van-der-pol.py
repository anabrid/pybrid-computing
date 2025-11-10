# Copyright (c) 2022-2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later
from pybrid.lucidac.lucipy import Circuit, LUCIDAC, time_series
import matplotlib.pyplot as plt
import numpy as np

###
# Create a Van der Pol oscillator circuit in lucipy-syntax
###

vdp = Circuit()                         # Create a circuit

eta = 4                                 # Nonlinearity parameter

mdy = vdp.int()                         # Integrators
y   = vdp.int(ic = 0.1)
y2  = vdp.mul(1)                        # Multipliers for nonlinear terms
fb  = vdp.mul(2)
c   = vdp.const()                       # Constant source

vdp.connect(fb, mdy, weight = -eta)
vdp.connect(y,  mdy, weight = -0.5)

vdp.connect(mdy, y, weight = 2)

vdp.connect(y, y2.a)                    # Compute y^2
vdp.connect(y, y2.b)

vdp.connect(y2,  fb.a, weight = -1)     # Build nonlinear feedback term
vdp.connect(c,   fb.a, weight = 0.25)
vdp.connect(mdy, fb.b)

vdp.probe(mdy, front_port=0)            # Connect to front panel probes
vdp.probe(y,   front_port=1)

vdp.measure(mdy)                        # Connect to ADC to sample data
vdp.measure(y)

###
# Auto-detect LUCIDAC-device (empty constructor) or:
# - set environment variable LUCIDAC_ENDPOINT to a connection string
# - pass the connection string directly
#
# where the connection string is `tcp://<LUCIDAC IP or hostname>:5732`.
###
luci    = LUCIDAC()

luci.set_circuit(vdp)                   # Assign circuit

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
for adc_key, values in run.data.items():
    x = time_series(sample_rate, len(values))
    plt.plot(x, values, label=adc_key[-1])
plt.xlabel("time / s")
plt.legend()
plt.grid()
plt.show()
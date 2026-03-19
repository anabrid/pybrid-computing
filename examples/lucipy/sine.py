# Copyright (c) 2022-2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later
from pybrid.lucipy import Circuit, LUCIDAC, time_series
import matplotlib.pyplot as plt
import numpy as np

###
# Create a simple sine/cosine oscillator circuit in lucipy-syntax
###

###
# Auto-detect LUCIDAC-device (empty constructor) or:
# - set environment variable LUCIDAC_ENDPOINT to a connection string
# - pass the connection string directly
#
# where the connection string is `tcp://<LUCIDAC IP or hostname>:5732`.
###
luci    = LUCIDAC()

c   = luci.create_circuit()             # Create a circuit

ic_sin  = -1                            # Initial value for the sine
omega   = .01 * (2.*np.pi)              # Oscillation frequency

sin = c.int(ic = ic_sin)                # Integrators for sine and cosine
cos = c.int()

c.connect(sin, cos, weight = +omega)    # Connect sine to cosine integrator
c.connect(cos, sin, weight = -omega)    # Connect cosine to sine integrator

c.probe(sin, adc_channel=0)           # Connect integrators to ADC
c.probe(cos, adc_channel=1)           # to sample data

###
# Settings for sampling and circuit execution
###
op_secs     = .05                       # Duration of OP cycle in seconds
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
for ix, values in enumerate(run.data):
    x = time_series(sample_rate, len(values))
    plt.plot(x, values, label=f"Probe {ix}")
plt.xlabel("time / s")
plt.legend()
plt.grid()
plt.show()
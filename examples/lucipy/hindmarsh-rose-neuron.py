# Copyright (c) 2022-2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later
"""
Hindmarsh-Rose Neuron Model

This example implements the Hindmarsh-Rose neuron model on the LUCIDAC.

Reference: Analog Paradigm Application Note 28
https://analogparadigm.com/downloads/alpaca_28.pdf
"""

from pybrid.lucipy import Circuit, LUCIDAC, time_series
import matplotlib.pyplot as plt
import numpy as np


###
# Create a Hindmarsh-Rose neuron model circuit in lucipy-syntax
###

###
# Auto-detect LUCIDAC-device (empty constructor) or:
# - set environment variable LUCIDAC_ENDPOINT to a connection string
# - pass the connection string directly
#
# where the connection string is `tcp://<LUCIDAC IP or hostname>:5732`.
###
luci    = LUCIDAC()

hr      = luci.create_circuit()         # Create a circuit

x   = hr.int(ic = +1.)                  # Integrators with initial conditions
y   = hr.int(ic = -1.)
z   = hr.int(ic = +1, slow = True)      # Slow dynamics for adaptation
x2  = hr.mul()                         # Multipliers for nonlinear terms
x3  = hr.mul()
c   = hr.const()                        # Constant source

hr.connect( x, x2.a)                    # Compute x^2
hr.connect( x, x2.b)

hr.connect( x, x3.a)                    # Compute x^3
hr.connect(x2, x3.b)

hr.connect(x3, x, weight = +4.)         # Fast subsystem (membrane potential)
hr.connect(x2, x, weight = +6.)
hr.connect( y, x, weight = +7.5)
hr.connect( z, x)
hr.connect( c, x)

hr.connect(x2, y, weight = 1.333)       # Recovery variable
hr.connect( y, y)
hr.connect( c, y, weight = -0.066)

hr.connect( x, z, weight = -0.4)        # Slow adaptation current
hr.connect( c, z, weight = +0.32)
hr.connect( z, z, weight = +0.1)

hr.probe(x, adc_channel=0)              # Connect integrators to ADC
hr.probe(y, adc_channel=1)              # to sample data
hr.probe(z, adc_channel=2)

###
# Settings for sampling and circuit execution
###
op_secs     = .2                        # Duration of OP cycle in seconds
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
for ix, values in enumerate(run.data):
    x = time_series(sample_rate, len(values))
    plt.plot(x, [-t for t in values], label=f"Probe {ix}")
plt.xlabel("time / s")
plt.legend()
plt.grid()
plt.show()
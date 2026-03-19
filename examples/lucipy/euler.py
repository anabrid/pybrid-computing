# Copyright (c) 2022-2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later
"""
Euler Spiral

This example implements the Euler spiral on the LUCIDAC.

Reference: Analog Paradigm Application Note 33
https://analogparadigm.com/downloads/alpaca_33.pdf
"""

from pybrid.lucipy import Circuit, LUCIDAC
import matplotlib.pyplot as plt
import numpy as np


###
# Create an Euler spiral circuit in lucipy-syntax
###

# Set to True to run the integrators "slower", i.e. setting k0=100
use_slow = True

###
# Auto-detect LUCIDAC-device (empty constructor) or:
# - set environment variable LUCIDAC_ENDPOINT to a connection string
# - pass the connection string directly
#
# where the connection string is `tcp://<LUCIDAC IP or hostname>:5732`.
###
luci    = LUCIDAC()

e   = luci.create_circuit()             # Create a circuit

ramp  = e.int(ic = 1, slow=use_slow)     # Integrator for a time linear ramp
const = e.const()                        # Constant for the time linear ramp

scm0  = e.mul()                          # These two multipliers and two
scm1  = e.mul()                          # integrators generate a sine/cosine
sci0  = e.int(ic = 1, slow=use_slow)     # with time varying frequency (see
sci1  = e.int(slow=use_slow)             # below).

x     = e.int(ic = -0.5, slow=use_slow)  # Integrators for x and
y     = e.int(ic = -0.5, slow=use_slow)  # y component of the spiral

e.connect(const, ramp, weight = -0.1)    # Integrate over a constant

e.connect(ramp, scm0.a)                  # Generate a sine/cosine pair
e.connect(sci1, scm0.b)                  # with varying frequency

e.connect(ramp, scm1.a)
e.connect(sci0, scm1.b)

e.connect(scm0, sci0, weight = +5.)      # Multiple connections to amplify
e.connect(scm0, sci0, weight = +5.)

e.connect(scm1, sci1, weight = -5.)
e.connect(scm1, sci1, weight = -5.)

e.connect(sci0, x, weight = 0.2)         # Compute the parameterized Euler
e.connect(sci1, y, weight = 0.2)         # spiral.

e.probe(x, adc_channel=0)                # Connect integrators to ADC
e.probe(y, adc_channel=1)                # to sample data

###
# Settings for sampling and circuit execution
###
op_secs     = .2                       # Duration of OP cycle in seconds
sample_rate = 100_000                  # Samples per second (max: 150_000 for each channel)

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
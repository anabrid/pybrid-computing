# Copyright (c) 2022-2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later
from pybrid.lucidac.lucipy import Circuit, LUCIDAC, time_series
import matplotlib.pyplot as plt
import numpy as np


###
# Create a Mathieu equation circuit in lucipy-syntax
###

m   = Circuit()                         # Create a circuit

# First we need an amplitude stabilized cosine signal. Since we do not have
# limiters at the moment, we use a van der Pol oscillator for that purpose.
# A small value for eta ensures spectral cleanliness.

eta = .1                                # Van der Pol nonlinearity parameter

mdy = m.int(slow=True)                  # Van der Pol oscillator integrators
y   = m.int(ic = -1, slow=True)
y2  = m.mul()                           # Multipliers for nonlinear terms
fb  = m.mul()
k   = m.const()                         # Constant source

m.connect(fb, mdy, weight = -eta * 2)   # We need cos(2t), so all inputs
m.connect(y,  mdy, weight = -0.5 * 2)   # to the integrators get a factor 2.

m.connect(mdy, y, weight = 2 * 2)

m.connect(y, y2.a)                      # Compute y^2
m.connect(y, y2.b)

m.connect(y2,  fb.a, weight = -1)       # Build nonlinear feedback term
m.connect(k,   fb.a, weight = 0.25)
m.connect(mdy, fb.b)

# Now for the actual Mathieu equation:
# These are the two parameters of Mathieu's equation which have to
# be varied to get a stability map. 0 <= a <= 8 and 0 <= q <= 5.
a   = 4                                 # Mathieu equation parameters
q   = 1.8

mdym= m.int()                           # Mathieu equation integrators
ym  = m.int(ic = 0.1)
p   = m.mul()                           # Multiplier for parametric term

m.connect(ym, mdym, weight = -a)
m.connect(p,  mdym, weight = q)

m.connect(mdym, ym)

m.connect(y, p.a)                       # Parametric excitation term
m.connect(ym, p.b, weight = 2)

m.measure(ym, adc_channel=0)            # Connect to ADC to sample data

###
# Auto-detect LUCIDAC-device (empty constructor) or:
# - set environment variable LUCIDAC_ENDPOINT to a connection string
# - pass the connection string directly
#
# where the connection string is `tcp://<LUCIDAC IP or hostname>:5732`.
###
luci    = LUCIDAC()

luci.set_circuit(m)                     # Assign circuit

###
# Settings for sampling and circuit execution
###
op_secs     = .05                       # Duration of OP cycle in seconds
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
for adc_key, values in run.data.items():
    x = time_series(sample_rate, len(values))
    plt.plot(x, values, label=adc_key[-1])
plt.xlabel("time / s")
plt.legend()
plt.grid()
plt.show()
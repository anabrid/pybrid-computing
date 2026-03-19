# Copyright (c) 2022-2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later
"""
Lorenz 96 Attractor

This example implements the Lorenz attractor on the LUCIDAC.

Reference: Analog Paradigm Application Note 61
https://analogparadigm.com/downloads/alpaca_61.pdf
"""

from pybrid.lucipy import Circuit, LUCIDAC
import matplotlib.pyplot as plt
import numpy as np

###
# Auto-detect LUCIDAC-device (empty constructor) or:
# - set environment variable LUCIDAC_ENDPOINT to a connection string
# - pass the connection string directly
#
# where the connection string is `tcp://<LUCIDAC IP or hostname>:5732`.
###
luci    = LUCIDAC()

l   = luci.create_circuit()             # Create a circuit

N   = 4

x   = []
m   = []
for i in range(N):
    x.append(l.int(slow=True))
    m.append(l.mul())

F = l.const()

for i in range(N):
    l.connect(x[i-1], m[i].a, weight=-1.)

    l.connect(x[i-2], m[i].b, weight=+1.)
    l.connect(x[i-3], m[i].b, weight=-1.)

    l.connect(m[i], x[i], weight=-2)
    l.connect(F, x[i], weight=-.05)
    l.probe(x[i], adc_channel=i)

###
# Settings for smapling and cirucit execution
###
op_secs     = 1.0                        # duration of OP cycle in seconds
sample_rate = 100_000                   # samples per second (max: 150_000 for each channel)

luci.set_daq(num_channels=4, sample_rate=sample_rate)
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
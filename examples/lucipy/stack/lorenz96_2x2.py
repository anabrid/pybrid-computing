# Copyright (c) 2022-2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later
"""
Lorenz96 with N=4 on two analog-coupled LUCIDACs (2 variables each).

Implements the generalized Lorenz-96 model (cf. Application Note 61,
https://analogparadigm.com/downloads/alpaca_61.pdf):

    dx_i/dt = A (x_{i+1} - x_{i-2}) x_{i-1} + B x_i + F

Each LUCIDAC computes two variables (l0: x0, x1; l1: x2, x3) and
exchanges signals via ACL (analog coupling links). A dedicated identity
multiplier on each device routes the received signals into the local
circuit.

Requires connecting analog inputs/outputs 0-1 pairwise (e.g. output 0 from LUCIDAC
0 connected to input 0 of LUCIDAC 1, ...).
"""
from pybrid.lucipy import LUCIDAC, time_series

import matplotlib.pyplot as plt
import numpy as np
import random

slow = True
F = 0.2
A = 5
B = 0.1666

# Generate stack of two LUCIDACs - enter IP addresses here or leave empty
# to use auto-discover.
stack = LUCIDAC()

l = [stack.create_circuit(d) for d in range(2)]
c = [l[0].const(), l[1].const()]
m_id = [l[0].mul(), l[1].mul()]

# Identity paths through the multiplier invert the signal once more,
# compensating for the integrator's output inversion. The result is
# that idx[0]/idx[1] carry the true value (+x_i) of remote signals on
# device 0, and idx[2]/idx[3] likewise on device 1.
idx = []
for ix in range(2):
    idx += [m_id[ix].a.id(), m_id[ix].b.id()]

x, m = [], []
for ix in range(2):
    x += [l[ix].int(slow=slow), l[ix].int(slow=slow)]
    m += [l[ix].mul(), l[ix].mul()]

# Each LUCIDAC sends both x-signals to the other device with the same in/out index.
inx, outx = [], []
for ix in range(2):
    outx += [l[ix].output(port=0), l[ix].output(port=1)]
    inx += [l[1 - ix].input(port=0), l[1 - ix].input(port=1)]

# Connect x signals to output ports
for ix in range(2):
    for port in range(2):
        l[ix].connect(x[2 * ix + port], outx[2 * ix + port])

# Connect received inputs to identity multipliers
for ix in range(2):
    l[ix].connect(inx[2 * (1 - ix)], m_id[ix].a)
    l[ix].connect(inx[2 * (1 - ix) + 1], m_id[ix].b)

###
# Lorenz-96 equations for all 4 variables
#
# dx_i/dt = A (x_{i+1} - x_{i-2}) x_{i-1} + B x_i + F
#
# Local integrator outputs are inverted (-x_i), so weights are negated.
# ID-path signals carry +x_i (already compensated), so weights match
# the equation directly.
###
for i in range(4):
    d = i // 2  # device index
    ip1, im2, im1 = (i + 1) % 4, (i - 2) % 4, (i - 1) % 4

    # Signal reference: local uses x[j], remote uses identity path
    def sig(j, d=d):
        return x[j] if j // 2 == d else idx[2 * d + j % 2]

    # Weight: local signals are inverted, so negate the desired equation
    # coefficient; remote identity paths carry +x, coefficient passes through.
    def w(j, coeff, d=d):
        return -coeff if j // 2 == d else coeff

    # Multiplier: (x_{i+1} - x_{i-2}) * x_{i-1}
    l[d].connect(sig(ip1), m[i].a, weight=w(ip1, 1.0))
    l[d].connect(sig(im2), m[i].a, weight=w(im2, -1.0))
    l[d].connect(sig(im1), m[i].b, weight=w(im1, 1.0))

    # Integration: dx_i/dt = A * mul_result + B * x_i + F
    l[d].connect(m[i], x[i], weight=A)
    l[d].connect(x[i], x[i], weight=B)
    l[d].connect(c[d], x[i], weight=F)

# Measurements
for i in range(4):
    l[i // 2].probe(x[i], adc_channel=i % 2)

sample_rate = 100_000
stack.set_daq(sample_rate=sample_rate)
stack.set_run(op_time=500_000_000)

run = stack.run()

# Plotting
n_signals = len(run.data)

fig = plt.figure(figsize=(14, 16))
fig.canvas.manager.set_window_title("Lorenz96 N=4 (2 LUCIDACs)")
gs = fig.add_gridspec(3, 2, hspace=0.15, wspace=0.05)

# Row 1: line plot of all signals, spanning both columns
ax_line = fig.add_subplot(gs[0, :])
for i, values in enumerate(run.data):
    t = time_series(sample_rate, len(values))
    ax_line.plot(t, values, label=f"Probe {i}")
ax_line.set_xlabel("time / s")
ax_line.set_ylabel("amplitude")
ax_line.grid()
ax_line.set_title("All Signals")

# Rows 2-3: 2x2 grid of 3D projections with randomly sampled signal triples
random.seed(42)
for row, col in [(1, 0), (1, 1), (2, 0), (2, 1)]:
    sel = random.sample(range(n_signals), 3)
    ax3d = fig.add_subplot(gs[row, col], projection='3d')
    ax3d.plot(
        run.data[sel[0]], run.data[sel[1]], run.data[sel[2]],
        ls="-", marker="+", markersize=1.5,
    )
    ax3d.set_xlabel("")
    ax3d.set_ylabel("")
    ax3d.set_zlabel("")
    ax3d.tick_params(axis='both', which='both', pad=0, labelsize=7)
    ax3d.set_box_aspect(None, zoom=1.25)
    label = f"Signals {sel[0]} / {sel[1]} / {sel[2]}"
    ax3d.text2D(-0.22, 0.5, label, transform=ax3d.transAxes,
                rotation=90, va="center", ha="center", fontsize=10)

plt.tight_layout()
plt.show()
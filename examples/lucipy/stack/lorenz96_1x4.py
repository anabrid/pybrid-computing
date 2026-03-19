# Copyright (c) 2022-2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later
"""
Lorenz96 with N=4 on a single LUCIDAC device.

Implements the generalized Lorenz-96 model (cf. Application Note 61,
https://analogparadigm.com/downloads/alpaca_61.pdf):

    dx_i/dt = A (x_{i+1} - x_{i-2}) x_{i-1} + B x_i + F

with cyclic indices (mod N) and parameters A, B, F below.
"""
from pybrid.lucipy import LUCIDAC, time_series

import matplotlib.pyplot as plt
import numpy as np
import random

slow = True
F = 0.2
A = 5
B = 0.1666

N = 4

# Run
stack = LUCIDAC()

l0 = stack.create_circuit(0)
c0 = l0.const()
x = [l0.int(slow=slow) for _ in range(N)]
m = [l0.mul() for _ in range(N)]

# Wire Lorenz-96: dx_i/dt = A*(x_{i+1} - x_{i-2})*x_{i-1} + B*x_i + F
# Integrator outputs are inverted (-x_i), so weight=-1 recovers +x_i.
for i in range(N):
    l0.connect(x[(i+1) % N], m[i].a, weight=-1.0)  # +x_{i+1}
    l0.connect(x[(i-2) % N], m[i].a)                # -x_{i-2}
    l0.connect(x[(i-1) % N], m[i].b, weight=-1.0)   # +x_{i-1}
    l0.connect(m[i], x[i], weight=A)
    l0.connect(x[i], x[i], weight=B)
    l0.connect(c0,   x[i], weight=F)

for i in range(N):
    l0.probe(x[i], adc_channel=i)

sample_rate = 100_000
stack.set_daq(sample_rate=sample_rate)
stack.set_run(op_time=500_000_000)

run = stack.run()

# Plotting
n_signals = len(run.data)

fig = plt.figure(figsize=(14, 16))
fig.canvas.manager.set_window_title("Lorenz96 N=4 (1 LUCIDAC)")
gs = fig.add_gridspec(3, 2, hspace=0.15, wspace=0.05)

# Row 1: line plot of all signals, spanning both columns
ax_line = fig.add_subplot(gs[0, :])
for i, values in enumerate(run.data):
    t = time_series(sample_rate, len(values))
    ax_line.plot(t, values, label=f"Probe {i}")
ax_line.set_xlabel("time / s")
ax_line.set_ylabel("amplitude")
# ax_line.legend()
ax_line.grid()
ax_line.set_title("All Signals")

# Rows 2-3: 2x2 grid of 3D projections with randomly sampled signal triples
random.seed(42)
for row, col in [(1, 0), (1, 1), (2, 0), (2, 1)]:
    idx = random.sample(range(n_signals), 3)
    ax3d = fig.add_subplot(gs[row, col], projection='3d')
    ax3d.plot(
        run.data[idx[0]], run.data[idx[1]], run.data[idx[2]],
        ls="-", marker="+", markersize=1.5,
    )
    ax3d.set_xlabel("")
    ax3d.set_ylabel("")
    ax3d.set_zlabel("")
    ax3d.tick_params(axis='both', which='both', pad=0, labelsize=7)
    ax3d.set_box_aspect(None, zoom=1.25)
    label = f"Signals {idx[0]} / {idx[1]} / {idx[2]}"
    ax3d.text2D(-0.22, 0.5, label, transform=ax3d.transAxes,
                rotation=90, va="center", ha="center", fontsize=10)

plt.tight_layout()
plt.show()

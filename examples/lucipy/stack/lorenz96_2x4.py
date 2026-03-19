# Copyright (c) 2022-2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later
"""
Lorenz96 with N=8 on two analog-coupled LUCIDACs (4 variables each).

Implements the generalized Lorenz-96 model (cf. Application Note 61,
https://analogparadigm.com/downloads/alpaca_61.pdf):

    dx_i/dt = A (x_{i+1} - x_{i-2}) x_{i-1} + B x_i + F

Each LUCIDAC computes four variables (l0: x0-x3; l1: x4-x7). Cross-device
signals are exchanged via ACL (analog coupling links). Some outputs are
pre-inverted (weight=-1) to compensate for the integrator's output
inversion, delivering the true mathematical value to the receiving device.

Requires connecting analog inputs/outputs 0-3 pairwise (e.g. output 0 from LUCIDAC
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

N = 8   # number of Lorenz-96 variables
K = 4   # variables per device

# Generate stack of two LUCIDACs - enter IP addresses here or leave empty
# to use auto-discover.
stack = LUCIDAC()

l = [stack.create_circuit(d) for d in range(2)]
c = [l[0].const(), l[1].const()]

x, m = [], []
for d in range(2):
    x += [l[d].int(slow=slow) for _ in range(K)]
    m += [l[d].mul() for _ in range(K)]

# ACL port layout per device d (4 ports each):
#   Port 0: x[K*d]   pre-inverted   → sends +x[K*d]
#   Port 1: x[K*d+2] raw            → sends -x[K*d+2]
#   Port 2: x[K*d+3] pre-inverted   → sends +x[K*d+3]
#   Port 3: x[K*d+3] raw            → sends -x[K*d+3]
#
# Pre-inverted outputs (weight=-1) deliver +x_i to the receiver:
#   (-1) * (-x_i) = +x_i  (compensates integrator inversion)
# Non-inverted outputs deliver the raw -x_i, which the receiver
# can use directly where the equation needs a negative sign.
outx = [[l[d].output(port=p) for p in range(K)] for d in range(2)]
inx = [[l[d].input(port=p) for p in range(K)] for d in range(2)]

for d in range(2):
    l[d].connect(x[K * d], outx[d][0], weight=-1.0)      # pre-inverted +x[K*d]
    l[d].connect(x[K * d + 2], outx[d][1])               # raw -x[K*d+2]
    l[d].connect(x[K * d + 3], outx[d][2], weight=-1.0)  # pre-inverted +x[K*d+3]
    l[d].connect(x[K * d + 3], outx[d][3])               # raw -x[K*d+3]

# ACL input lookup: maps (signal_index, desired_sign) to input element on
# device d. The sign indicates what the physical ACL input carries:
# +1 for pre-inverted +x, -1 for raw -x.
acl = [{} for _ in range(2)]
for d in range(2):
    od = 1 - d
    acl[d][(K * od, +1)]     = inx[d][0]  # port 0 receives +x[K*od]
    acl[d][(K * od + 2, -1)] = inx[d][1]  # port 1 receives -x[K*od+2]
    acl[d][(K * od + 3, +1)] = inx[d][2]  # port 2 receives +x[K*od+3]
    acl[d][(K * od + 3, -1)] = inx[d][3]  # port 3 receives -x[K*od+3]

###
# Lorenz-96 equations for all 8 variables
#
# dx_i/dt = A (x_{i+1} - x_{i-2}) x_{i-1} + B x_i + F
#
# Local integrator outputs are inverted (-x_i), so weights are negated.
# Pre-compensated ACL inputs carry +x_i, raw ACL inputs carry -x_i;
# the ACL layout is chosen so that all remote connections use default
# weight=+1.
###
for i in range(N):
    d = i // K  # device index
    ip1, im2, im1 = (i + 1) % N, (i - 2) % N, (i - 1) % N

    def sig(j, coeff, d=d):
        """Return (element, weight) for signal j with equation coefficient coeff."""
        if j // K == d:
            # Local: integrator output is -xj, negate coefficient to compensate
            return x[j], -coeff
        else:
            # Remote: ACL input already carries the correctly-signed signal
            return acl[d][(j, coeff)], 1.0

    # Multiplier: (x_{i+1} - x_{i-2}) * x_{i-1}
    src, wt = sig(ip1, 1.0)
    l[d].connect(src, m[i].a, weight=wt)
    src, wt = sig(im2, -1.0)
    l[d].connect(src, m[i].a, weight=wt)
    src, wt = sig(im1, 1.0)
    l[d].connect(src, m[i].b, weight=wt)

    # Integration: dx_i/dt = A * mul_result + B * x_i + F
    l[d].connect(m[i], x[i], weight=A)
    l[d].connect(x[i], x[i], weight=B)
    l[d].connect(c[d], x[i], weight=F)

# Measurements
for i in range(N):
    l[i // K].probe(x[i], adc_channel=i % K)

sample_rate = 100_000
stack.set_daq(sample_rate=sample_rate)
stack.set_run(op_time=500_000_000)

run = stack.run()

# Plotting
n_signals = len(run.data)

fig = plt.figure(figsize=(14, 16))
fig.canvas.manager.set_window_title("Lorenz96 N=8 (2 LUCIDACs)")
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
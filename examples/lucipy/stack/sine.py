# Copyright (c) 2022-2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later
"""
4 Harmonic oscillators on 2, analog-coupled LUCIDACs

Requires connecting analog inputs/outputs 0-3 pairwise (e.g. output 0 from LUCIDAC
0 connected to input 0 of LUCIDAC 1, ...).
"""
from pybrid.lucipy import LUCIDAC, time_series

import matplotlib.pyplot as plt

# generate stack of two LUCIDACs - enter IP addresses here or leave empty
# to use auto-discover
stack = LUCIDAC()

# first LUCIDAC; ACL 0 out (1.0), ACL 0 in
l0 = stack.create_circuit(0)
l0_itor0, l0_itor1, l0_itor2, l0_itor3 = l0.int(ic=-0.105), l0.int(ic=-0.21), l0.int(ic=-0.42), l0.int(ic=-0.84)
l0_input0, l0_input1, l0_input2, l0_input3 = l0.input(port=0), l0.input(port=1), l0.input(port=2), l0.input(port=3)
l0_output0, l0_output1, l0_output2, l0_output3 = l0.output(port=0), l0.output(port=1), l0.output(port=2), l0.output(port=3)

l0.connect(l0_itor0, l0_output0)
l0.connect(l0_input0, l0_itor0)
l0.connect(l0_itor1, l0_output1)
l0.connect(l0_input1, l0_itor1)
l0.connect(l0_itor2, l0_output2)
l0.connect(l0_input2, l0_itor2)
l0.connect(l0_itor3, l0_output3)
l0.connect(l0_input3, l0_itor3)

l0.probe(l0_itor0, adc_channel=0)
l0.probe(l0_itor1, adc_channel=1)
l0.probe(l0_itor2, adc_channel=2)
l0.probe(l0_itor3, adc_channel=3)

# second LUCIDAC; ACL 0 out (-1.0), ACL 0 in
l1 = stack.create_circuit(1)
l1_itor0, l1_itor1, l1_itor2, l1_itor3 = l1.int(ic=-0.105), l1.int(ic=-0.21), l1.int(ic=-0.42), l1.int(ic=-0.84)
l1_input0, l1_input1, l1_input2, l1_input3 = l1.input(port=0), l1.input(port=1), l1.input(port=2), l1.input(port=3)
l1_output0, l1_output1, l1_output2, l1_output3 = l1.output(port=0), l1.output(port=1), l1.output(port=2), l1.output(port=3)

l1.connect(l1_itor0, l1_output0, weight=-1)
l1.connect(l1_input0, l1_itor0)
l1.connect(l1_itor1, l1_output1, weight=-1)
l1.connect(l1_input1, l1_itor1)
l1.connect(l1_itor2, l1_output2, weight=-1)
l1.connect(l1_input2, l1_itor2)
l1.connect(l1_itor3, l1_output3, weight=-1)
l1.connect(l1_input3, l1_itor3)

l1.probe(l1_itor0, adc_channel=0)
l1.probe(l1_itor1, adc_channel=1)
l1.probe(l1_itor2, adc_channel=2)
l1.probe(l1_itor3, adc_channel=3)

sample_rate = 100_000
stack.set_daq(sample_rate=sample_rate)
stack.set_run(op_time=10_000_000)

run = stack.run()

for ix, values in enumerate(run.data):
    x = time_series(sample_rate, len(values))
    plt.plot(x, values, label=f"Probe {ix}")
plt.xlabel("time / s")
plt.legend()
plt.grid()
plt.show()
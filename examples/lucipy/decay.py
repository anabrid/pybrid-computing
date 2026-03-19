# Copyright (c) 2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

from pybrid.lucipy import Circuit, LUCIDAC, time_series
import matplotlib.pyplot as plt
import numpy as np

###
# Create a simple circuit modelling exponential decay
###

_lambda = 0.3       # decay rate
_n0 = 0.8           # initial quantity

luci    = LUCIDAC()

c = luci.create_circuit()

N = c.int(ic = -_n0, slow=True)

c.connect(N, N, weight = _lambda)       # Need to use _lambda without the (-1) as
                                        # integrators in the LUCIDAC already invert

c.probe(N, adc_channel=0)

from pybrid.base.proto.io import ProtoIO
pb_file = c.to_config()
ProtoIO.store_module(pb_file.module, "decay.apb")
print("Config written to decay.apb")

###
# Settings for sampling and circuit execution
###
op_secs     = .5                        # Duration of OP cycle in seconds
sample_rate = 100_000                   # Samples per second (max: 150_000 for each channel)

luci.set_daq(num_channels=2, sample_rate=sample_rate)
luci.set_run(ic_time = 1_000, op_time=int(op_secs * 1_000_000_000))

###
# Run circuit and start sampling
###
run = luci.run()

for ix, values in enumerate(run.data):
    x = time_series(sample_rate, len(values))
    plt.plot(x, values, label=f"Probe {ix}")
plt.xlabel("time / s")
plt.legend()
plt.grid()
plt.show()
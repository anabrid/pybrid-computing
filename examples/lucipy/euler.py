from pybrid.lucipy import Circuit, LUCIDAC, time_series
import matplotlib.pyplot as plt
import numpy as np

luci = LUCIDAC()

e   = Circuit()                           # Create a circuit

ramp  = e.int(ic = 1)                   # Integrator for a time linear ramp
const = e.const()                       # Constant for the time linear ramp

scm0  = e.mul()                         # These two multipliers and two
scm1  = e.mul()                         # integrators generate a sine/cosine
sci0  = e.int(ic = 1)                   # with time varying frequency (see 
sci1  = e.int()                         # below).

x     = e.int(ic = 0.65)                # Integrators for x and
y     = e.int(ic = 0.65)                # y component of the spiral

e.connect(const, ramp, weight = -0.1)   # Integrate over a constant

e.connect(ramp, scm0.a)                 # Generate a sine/cosine pair
e.connect(sci1, scm0.b)                 # with varying frequency

e.connect(ramp, scm1.a)                 
e.connect(sci0, scm1.b)

e.connect(scm0, sci0, weight = +5.)
e.connect(scm0, sci0, weight = +5.)

e.connect(scm1, sci1, weight = -5.)
e.connect(scm1, sci1, weight = -5.)

e.connect(sci0, x, weight = 0.6)        # Compute the parameterized Euler
e.connect(sci1, y, weight = 0.6)        # spiral.

e.measure(x, adc_channel=0)
e.measure(y, adc_channel=1)

luci.set_circuit(e)



op_secs     = .1                        # duration of OP cycle in seconds
sample_rate = 100_000                   # samples per second

luci.set_daq(num_channels=3, sample_rate=sample_rate)
luci.set_run(ic_time = 1_000, op_time=int(op_secs * 1_000_000_000))

run = luci.run()

ax = plt.figure().add_subplot()
ax.plot(*np.array(list(run.data.values())), ls="", marker=".", markersize=1.5)
ax.set_xlabel("X")
ax.set_ylabel("Y")
plt.show()

"""
plot looks weird
scaling problems
"""
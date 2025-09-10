from pybrid.lucipy import Circuit, LUCIDAC
import matplotlib.pyplot as plt
import numpy as np

op_secs = .1 # duration of OP cycle in seconds
sample_rate = 50_000

r = Circuit()                           # Create a circuit

x     = r.int(ic = .066)
my    = r.int()
mz    = r.int()
prod  = r.mul()
const = r.const(1)

r.connect(my,    x, weight = -0.8)
r.connect(mz,    x, weight = -2.3)

r.connect(x,     my, weight = +1.25)
r.connect(my,    my, weight = -0.2)

r.connect(const, mz, weight = +0.005)
r.connect(prod,  mz, weight = +5)
r.connect(prod,  mz, weight = +5)
r.connect(prod,  mz, weight = +5)

r.connect(mz,    prod.a, weight = -1)
r.connect(x,     prod.b)
r.connect(const, prod.b, weight = -0.3796)

r.measure(x,  adc_channel=0)
r.measure(my, adc_channel=1)

luci = LUCIDAC()
luci.set_circuit(r)
luci.set_daq(num_channels=3, sample_rate=sample_rate)
luci.set_run(ic_time = 1_000, op_time=int(op_secs * 1_000_000_000))
run = luci.run()

def time_series(sample_rate, sample_count):
    sample_period_micros = 1_000_000 // sample_rate
    sample_period = sample_period_micros / 1_000_000
    real_sample_time = sample_period * (sample_count - 1)
    return np.linspace(0, real_sample_time, sample_count)

ax = plt.figure().add_subplot()
ax.plot(*np.array(list(run.data.values())[:2]), ls="", marker=".", markersize=1.5)
ax.set_xlabel("X")
ax.set_ylabel("Y")
plt.show()

"""
works
"""
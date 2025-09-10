from pybrid.lucipy import Circuit, LUCIDAC
import matplotlib.pyplot as plt
import numpy as np

op_secs = .01 # duration of OP cycle in seconds
sample_rate = 10_000

hc = Circuit()                          # Create a circuit

fs = False

mw   = hc.int(slow = fs, ic = .01)
z    = hc.int(slow = fs)
my   = hc.int(slow = fs)
x    = hc.int(slow = fs)
x2   = hc.mul()
x4   = hc.mul()
mwx4 = hc.mul()

hc.connect(mwx4, mw, weight = 0.8)
hc.connect(x,    mw, weight = -0.02)
hc.connect(my,   mw, weight = 0.03)
hc.connect(z,    mw, weight = -0.175)

hc.connect(mw, z, weight = 0.2)

hc.connect(z, my, weight = 0.1666)

hc.connect(my, x, weight = 0.15)
hc.connect(x,  x, weight = 0.007)

hc.connect(x, x2.a, weight = 2)
hc.connect(x, x2.b, weight = 2)

hc.connect(x2, x4.a)
hc.connect(x2, x4.b)

hc.connect(x4, mwx4.a)
hc.connect(mw, mwx4.b, weight = 2)

hc.probe(mw, front_port=4)
hc.probe(x,  front_port=5)
hc.probe(my, front_port=6)
hc.probe(z,  front_port=7)

hc.measure(mw, adc_channel=0)
hc.measure(x,  adc_channel=1)
hc.measure(my, adc_channel=2)
hc.measure(z,  adc_channel=3)

luci = LUCIDAC()
luci.set_circuit(hc)
luci.set_daq(num_channels=3, sample_rate=sample_rate)
luci.set_run(ic_time = 1_000, op_time=int(op_secs * 1_000_000_000))
run = luci.run()

def time_series(sample_rate, sample_count):
    sample_period_micros = 1_000_000 // sample_rate
    sample_period = sample_period_micros / 1_000_000
    real_sample_time = sample_period * (sample_count - 1)
    return np.linspace(0, real_sample_time, sample_count)

for adc_key, values in run.data.items():
    x = time_series(sample_rate, len(values))
    plt.plot(x, values, label=adc_key[-1])
plt.xlabel("time / s")
plt.legend()
plt.grid()
plt.show()

"""
works
"""
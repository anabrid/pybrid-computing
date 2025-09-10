from pybrid.lucipy import Circuit, LUCIDAC
import matplotlib.pyplot as plt
import numpy as np

op_secs = .05 # duration of OP cycle in seconds
sample_rate = 50_000

hr = Circuit()                          # Create a circuit

mx  = hr.int(ic = +1.)
y   = hr.int(ic = +1.)
mz  = hr.int(ic = -1., slow = True)
x2  = hr.mul(1)
mx3 = hr.mul(2)
c   = hr.const()

hr.connect(c,   mx)
hr.connect(mx3, mx, weight = 4.)
hr.connect(x2,  mx, weight = 6.)
hr.connect(y,   mx, weight = 7.5)
hr.connect(mz,  mx)

hr.connect(mx, mx3.a)
hr.connect(x2, mx3.b)

hr.connect(mx, x2.a)
hr.connect(mx, x2.b)

hr.connect(x2, y, weight = +1.333)
hr.connect(c,  y, weight = -0.066)
hr.connect(y,  y)

hr.connect(mx, mz, weight = -0.4)
hr.connect(c,  mz, weight = +0.32)
hr.connect(mz, mz, weight = +0.1)

# hr.probe(mx, front_port=5, weight=-1)
# hr.probe(y,  front_port=6)
# hr.probe(mz, front_port=7, weight=-1)

hr.measure(mx, adc_channel=0)
hr.measure(y,  adc_channel=1)
hr.measure(mz, adc_channel=2)

luci = LUCIDAC()
luci.set_circuit(hr)
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
results are wrong, maybe?
"""
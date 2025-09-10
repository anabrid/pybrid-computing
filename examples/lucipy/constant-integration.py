from pybrid.lucipy import Circuit, LUCIDAC
import matplotlib.pyplot as plt
import numpy as np

op_secs = 0.01 # duration of OP cycle in seconds
sample_rate = 10_000

c = Circuit()
const0 = c.const()
integrators = []
for i in range(8):
    integrators.append(c.int(ic=-0.1 * i))

for i in range(8):    
    c.connect(const0, integrators[i], weight=0.001 * i)
    c.measure(integrators[i], adc_channel=i)

luci = LUCIDAC()
luci.set_circuit(c)
luci.set_daq(num_channels=8, sample_rate=sample_rate)
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
plt.ylim(-1.5, 1.5)
plt.grid()
plt.show()
from pybrid.lucipy import Circuit, LUCIDAC
import matplotlib.pyplot as plt
import numpy as np

luci = LUCIDAC()

c = Circuit()

f = 0.01

const0 = c.const()
integrators = []

for i in range(8):
    integrators.append(c.int(ic=-1.))
    # c.connect(integrators[i], integrators[i], weight=f)
    c.connect(const0, integrators[i], weight=f)
    c.measure(integrators[i], adc_channel=i)



op_secs     = 0.01                      # duration of OP cycle in seconds
sample_rate = 50_000                    # samples per second

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
    plt.plot(x, np.array(values), label=f"{adc_key[-1]} IC=1.0 F=0.", ls="-", marker="")
# plt.plot(x, np.exp(-x * 1 / op_secs), label=f"ideal", ls=":")
plt.plot(x, (1 - x * f * 100 / op_secs), label=f"ideal", ls=":")
plt.xlabel("time / s")
plt.legend()
plt.grid()
plt.show()
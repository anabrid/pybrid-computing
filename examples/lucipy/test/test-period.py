from pybrid.lucipy import Circuit, LUCIDAC
import matplotlib.pyplot as plt
import numpy as np



c = Circuit()

ic_sin = -0.5 # initial value for the SIN component
omega = 1.0

int_sin = c.int(ic = ic_sin)
int_cos = c.int()

c.connect(int_sin, int_cos, weight = +omega)
c.connect(int_cos, int_sin, weight = -omega)
c.measure(int_sin, adc_channel=0)
c.measure(int_cos, adc_channel=1)



op_secs = 0.01 # duration of OP cycle in seconds
sample_rate = 100_000

luci = LUCIDAC()
luci.set_circuit(c)
luci.set_daq(num_channels=2, sample_rate=sample_rate)
luci.set_run(ic_time = 1_000, op_time=int(op_secs * 1_000_000_000))

run = luci.run()

def time_series(sample_rate, sample_count):
    sample_period_micros = 1_000_000 // sample_rate
    sample_period = sample_period_micros / 1_000_000
    real_sample_time = sample_period * (sample_count - 1)
    return np.linspace(0, real_sample_time, sample_count)

for adc_key, values in run.data.items():
    x = time_series(sample_rate, len(values))
    loc = np.argwhere(np.diff(np.where(np.array(values)>0,-1, 1)) == 2)
    print(loc)
    plt.plot(x, values, label=adc_key[-1])
plt.xlabel("time / s")
plt.legend()
plt.grid()
plt.show()

"""
works
"""
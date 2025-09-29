from pybrid.lucipy import Circuit, LUCIDAC, time_series
import matplotlib.pyplot as plt
import numpy as np



t    = Circuit()



c   = t.const()
m   = []

for i in range(4):
    m.append(t.mul())
    t.connect(c, m[i].a, weight=i//2)
    t.connect(c, m[i].b, weight=i%2)
    t.measure(m[i], adc_channel=i)



op_secs     = 1.                        # duration of OP cycle in seconds
sample_rate = 100_000                   # samples per second

luci = LUCIDAC()
luci.set_circuit(t)
luci.set_daq(num_channels=8, sample_rate=sample_rate)
luci.set_run(ic_time = 1_000, op_time=int(op_secs * 1_000_000_000))

run = luci.run()



for i, (adc_key, values) in enumerate(run.data.items()):
    x = time_series(sample_rate, len(values))
    plt.plot(x, np.array(values), label=f"{adc_key[-1]} - {i//2} x {i%2}")
plt.xlabel("time / s")
plt.ylabel("Absolute deviation")
plt.legend()
# plt.ylim(-1.5, 1.5)
plt.grid()
plt.show()
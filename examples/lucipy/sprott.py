from pybrid.lucipy import Circuit, LUCIDAC
import matplotlib.pyplot as plt
import numpy as np

op_secs = .1 # duration of OP cycle in seconds
sample_rate = 50_000

sprott = Circuit()
scale = 0.7
mx      = sprott.int(ic = .1)
my      = sprott.int()
mz      = sprott.int()
mxy     = sprott.mul()
yz      = sprott.mul()
const   = sprott.const()

sprott.connect(yz, mx, weight = 10 * scale)         # x' = yz

sprott.connect(mx, my, weight = -1 * scale)         # y' = x - y
sprott.connect(my, my, weight = +1 * scale)
sprott.connect(const, mz, weight = 0.1 * scale)     # z' = 1 - xy (scaled!)

sprott.connect(mxy, mz, weight = 10 * scale)

sprott.connect(mx, mxy.a, weight = +1 * scale)                  # -xy
sprott.connect(my, mxy.b, weight = -1 * scale)

sprott.connect(my, yz.a)                    # yz
sprott.connect(mz, yz.b)

sprott.measure(mx, adc_channel=0)
sprott.measure(my, adc_channel=1)
sprott.measure(mz, adc_channel=2)

luci = LUCIDAC()
luci.set_circuit(sprott)
luci.set_daq(num_channels=3, sample_rate=sample_rate)
luci.set_run(ic_time = 1_000, op_time=int(op_secs * 1_000_000_000))
run = luci.run()

def time_series(sample_rate, sample_count):
    sample_period_micros = 1_000_000 // sample_rate
    sample_period = sample_period_micros / 1_000_000
    real_sample_time = sample_period * (sample_count - 1)
    return np.linspace(0, real_sample_time, sample_count)

ax = plt.figure().add_subplot(projection='3d')
ax.plot(*np.array(list(run.data.values())), ls="", marker=".", markersize=1.5)
ax.set_xlabel("X")
ax.set_ylabel("Y")
ax.set_zlabel("Z")
plt.show()

"""
works
"""
from pybrid.lucipy import Circuit, LUCIDAC
import matplotlib.pyplot as plt
import numpy as np

op_secs = 1.0 # duration of OP cycle in seconds
sample_rate = 10_000

a = 1.0
b = 2.8
c = 2.666 / 10

l = Circuit()                           # Create a circuit

mx = l.int(ic = -0.1, slow=True)
my = l.int(ic = +0.3, slow=True)
mz = l.int(ic = +0.1, slow=True)
xz = l.mul()
xy = l.mul()

l.connect(mx, xz.a)                     # Product -x * -z = xz
l.connect(mz, xz.b, weight = 2)

l.connect(mx, xy.a)                     # Product -x * -y = xy
l.connect(my, xy.b)

l.connect(my, mx, weight = -a)
l.connect(mx, mx, weight = a)

l.connect(mx, my, weight = -b)
l.connect(xz, my, weight = -5.)
l.connect(my, my, weight = 0.1)

l.connect(xy, mz, weight = 2.5)
l.connect(mz, mz, weight = c)

l.measure(mx, adc_channel=0)
l.measure(my, adc_channel=1)
l.measure(mz, adc_channel=2)

# l.probe(mx, front_port=0, weight=+0.8)
# l.probe(my, front_port=1, weight=+1.0)
# l.probe(mz, front_port=2, weight=-0.8)

luci = LUCIDAC("tcp://192.168.150.78:5732")
luci.set_circuit(l)
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
from pybrid.lucipy import Circuit, LUCIDAC, time_series
import matplotlib.pyplot as plt
import numpy as np

luci    = LUCIDAC()

l   = Circuit()                         # Create a circuit

a   = 1.0
b   = 2.8
c   = 2.666 / 10

mx  = l.int()
my  = l.int()
mz  = l.int(ic = .3)
xz  = l.mul()
xy  = l.mul()

l.connect(mx, xz.a)                     # Product -x * -z = xz
l.connect(mz, xz.b, weight = 2)

l.connect(mx, xy.a)                     # Product -x * -y = xy
l.connect(my, xy.b)

l.connect(my, mx, weight = -a)
l.connect(mx, mx, weight = +a)

l.connect(mx, my, weight = -b)
l.connect(xz, my, weight = -5)
l.connect(my, my, weight = .1)

l.connect(xy, mz, weight = 2.5)
l.connect(mz, mz, weight = c)

l.measure(mx, adc_channel = 0)
l.measure(my, adc_channel = 1)
l.measure(mz, adc_channel = 2)

luci.set_circuit(l)                     # Apply circuit



op_secs     = .1                        # duration of OP cycle in seconds
sample_rate = 100_000                   # samples per second

luci.set_daq(num_channels=3, sample_rate=sample_rate)
luci.set_run(ic_time = 1_000, op_time=int(op_secs * 1_000_000_000))

run = luci.run()



ax = plt.figure().add_subplot(projection='3d')
ax.plot(*np.array(list(run.data.values())), ls="", marker=".", markersize=1.5)
ax.set_xlabel("X")
ax.set_ylabel("Y")
ax.set_zlabel("Z")
plt.show()

"""
works
"""
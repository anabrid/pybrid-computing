from pybrid.lucipy import Circuit, LUCIDAC, time_series
import matplotlib.pyplot as plt
import numpy as np

luci    = LUCIDAC()

sprott  = Circuit()                     # Create a circuit

a = 1.66

x = sprott.int(ic = 0.2)
y = sprott.int()
z = sprott.int()
y2 = sprott.mul()

sprott.connect( y, x, weight = +0.5)

sprott.connect( z, y)

sprott.connect( z, z, weight = a)
sprott.connect( x, z, weight = +2.)
sprott.connect(y2, z, weight = +5.)

sprott.connect(y, y, weight = +0.1)

sprott.connect( y, y2.a)
sprott.connect( y, y2.b)

sprott.measure(x, adc_channel=0)
sprott.measure(y, adc_channel=1)
sprott.measure(z, adc_channel=2)

luci.set_circuit(sprott)



op_secs = .1                            # duration of OP cycle in seconds
sample_rate = 100_000                   # samples per second

luci.set_daq(num_channels=3, sample_rate=sample_rate)
luci.set_run(ic_time = 1_000, op_time=int(op_secs * 1_000_000_000))

run = luci.run()

ax = plt.figure().add_subplot(projection='3d')
ax.plot(*np.array(list(run.data.values())), ls="-", marker=".", markersize=1.5)
ax.set_xlabel("X")
ax.set_ylabel("Y")
ax.set_zlabel("Z")
plt.show()

"""
plot looks weird
scaling problems
"""
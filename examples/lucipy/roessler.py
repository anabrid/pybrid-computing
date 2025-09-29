from pybrid.lucipy import Circuit, LUCIDAC
import matplotlib.pyplot as plt
import numpy as np

luci    = LUCIDAC()

r   = Circuit()                         # Create a circuit

x   = r.int(ic = .066)
y   = r.int()
z   = r.int()
m   = r.mul()
c   = r.const()

r.connect(y, x, weight = -0.8)
r.connect(z, x, weight = -2.3)

r.connect(x, y, weight = +1.25)
r.connect(y, y, weight = -0.2)

r.connect(c, z, weight = +0.005)
r.connect(m, z, weight = +5.)
r.connect(m, z, weight = +5.)
r.connect(m, z, weight = +5.)

r.connect(z, m.a, weight = -1)
r.connect(x, m.b)
r.connect(c, m.b, weight = -0.3796)

r.measure(x,  adc_channel=0)
r.measure(y, adc_channel=1)

luci.set_circuit(r)



op_secs     = .1                        # duration of OP cycle in seconds
sample_rate = 100_000                   # samples per second

luci.set_daq(num_channels=2, sample_rate=sample_rate)
luci.set_run(ic_time = 1_000, op_time=int(op_secs * 1_000_000_000))

run = luci.run()



ax = plt.figure().add_subplot()
ax.plot(*np.array(list(run.data.values())[:2]), ls="", marker=".", markersize=1.5)
ax.set_xlabel("X")
ax.set_ylabel("Y")
plt.show()

"""
works
"""
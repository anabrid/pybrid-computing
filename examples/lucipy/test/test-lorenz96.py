from pybrid.lucipy import Circuit, LUCIDAC, time_series
import matplotlib.pyplot as plt
import numpy as np

luci    = LUCIDAC()

l   = Circuit()                         # Create a circuit

N   = 4

x   = []
m   = []
for i in range(N):
    x.append(l.int())
    m.append(l.mul())

F = l.const()

for i in range(N):
    l.connect(x[i-1], m[i].a, weight=-1.)

    l.connect(x[i-2], m[i].b, weight=+1.)
    l.connect(x[i-3], m[i].b, weight=-1.)

    l.connect(m[i], x[i], weight=-.666)
    l.connect(m[i], x[i], weight=-.666)
    l.connect(m[i], x[i], weight=-.666)
    l.connect(x[i], x[i], weight=+.1)
    l.connect(F, x[i], weight=-.10)
    l.measure(x[i], adc_channel=i)

luci.set_circuit(l)



op_secs     = .1                        # duration of OP cycle in seconds
sample_rate = 100_000                   # samples per second

luci.set_daq(num_channels=3, sample_rate=sample_rate)
luci.set_run(ic_time = 1_000, op_time=int(op_secs * 1_000_000_000))

run = luci.run()



data = np.array(list(run.data.values()))
ax = plt.figure().add_subplot()
ax.plot(-data[0], -data[1], ls="-", marker="", markersize=1.5)
ax.scatter(-data[0][0], -data[1][0])
ax.set_xlabel("X")
ax.set_ylabel("Y")
plt.show()

"""
works
"""
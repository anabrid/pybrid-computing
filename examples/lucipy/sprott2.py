from pybrid.lucipy import Circuit, LUCIDAC
import matplotlib.pyplot as plt
import numpy as np

op_secs = .1 # duration of OP cycle in seconds
sample_rate = 50_000

a = 1.89

sprott = Circuit()                           # Create a circuit

x = sprott.int(ic = 0.2)
y = sprott.int()
z = sprott.int()
y2 = sprott.mul()
# c = sprott.const()


sprott.connect( y, x, weight = +0.5)

sprott.connect( z, y)

# sprott.connect( c, z, weight = +2.)
sprott.connect( z, z, weight = a)
sprott.connect( x, z, weight = +2.)
sprott.connect(y2, z, weight = +5.)

sprott.connect(y, y, weight = +0.1)

sprott.connect( y, y2.a)
sprott.connect( y, y2.b)

# sprott.probe(x, front_port=0)
# sprott.probe(y, front_port=1)

sprott.measure(x, adc_channel=0)
sprott.measure(y, adc_channel=1)
sprott.measure(z, adc_channel=2)

luci = LUCIDAC()
luci.set_log_level("DEBUG")
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
ax.plot(*np.array(list(run.data.values())), ls="-", marker=".", markersize=1.5)
ax.set_xlabel("X")
ax.set_ylabel("Y")
ax.set_zlabel("Z")
plt.show()

"""
plot looks weird
scaling problems
"""
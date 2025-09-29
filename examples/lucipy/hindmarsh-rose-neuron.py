from pybrid.lucipy import Circuit, LUCIDAC, time_series
import matplotlib.pyplot as plt
import numpy as np

luci    = LUCIDAC()

hr      = Circuit()                     # Create a circuit

x   = hr.int(ic = +1.)
y   = hr.int(ic = -1.)
z   = hr.int(ic = +1, slow = True)
x2  = hr.mul(1)
x3  = hr.mul(2)
c   = hr.const()

hr.connect( x, x2.a)
hr.connect( x, x2.b)

hr.connect( x, x3.a)
hr.connect(x2, x3.b)

hr.connect(x3, x, weight = +4.)
hr.connect(x2, x, weight = +6.)
hr.connect( y, x, weight = +7.5)
hr.connect( z, x)
hr.connect( c, x)

hr.connect(x2, y, weight = 1.333)
hr.connect( y, y)
hr.connect( c, y, weight = -0.066)

hr.connect( x, z, weight = -0.4)
hr.connect( c, z, weight = +0.32)
hr.connect( z, z, weight = +0.1)

hr.measure(x, adc_channel=0)
hr.measure(y, adc_channel=1)
hr.measure(z, adc_channel=2)

luci.set_circuit(hr)


op_secs     = .2                        # duration of OP cycle in seconds
sample_rate = 100_000                   # samples per second

luci.set_daq(num_channels=3, sample_rate=sample_rate)
luci.set_run(ic_time = 1_000, op_time=int(op_secs * 1_000_000_000))

run = luci.run()



for adc_key, values in run.data.items():
    x = time_series(sample_rate, len(values))
    plt.plot(x, values, label=adc_key[-1])
plt.xlabel("time / s")
plt.legend()
plt.grid()
plt.show()

"""
works
"""
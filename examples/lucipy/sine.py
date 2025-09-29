from pybrid.lucipy import Circuit, LUCIDAC, time_series
import matplotlib.pyplot as plt
import numpy as np



luci    = LUCIDAC()

c   = Circuit()                         # Create a circuit

ic_sin  = -1                            # initial value for the sine
omega   = .01 * (2.*np.pi)              # oscillation frequency

sin = c.int(ic = ic_sin)
cos = c.int()

c.connect(sin, cos, weight = +omega)
c.connect(cos, sin, weight = -omega)

c.measure(sin, adc_channel=0)
c.measure(cos, adc_channel=1)

luci.set_circuit(c)



op_secs     = .05                       # duration of OP cycle in seconds
sample_rate = 100_000                   # samples per second

luci.set_daq(num_channels=2, sample_rate=sample_rate)
luci.set_run(ic_time = 1_000, op_time=int(op_secs * 1_000_000_000))

run = luci.run()



for adc_key, values in run.data.items():
    x = time_series(sample_rate, len(values))
    loc = np.argwhere(np.diff(np.where(np.array(values)>0,-1, 1)) == 2)
    plt.plot(x, values, label=adc_key[-1])
plt.xlabel("time / s")
plt.legend()
plt.grid()
plt.show()

"""
works
"""
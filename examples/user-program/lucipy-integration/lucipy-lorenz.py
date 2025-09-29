##
# Simple harmonic oscillators, repeated for a number of times. This example uses
# the run configurations `repetitive` parameter 
## 

import json
# from lucipy import Circuit, LUCIDAC
from lucipy import LUCIDAC, Circuit, Route, Connection, Simulation
import matplotlib.pyplot as plt
import numpy as np


# number of cycles that should be executed
num_cycles = 1

a = 1.0
b = 2.8
c = 2.666 / 10

m = Circuit()                           # Create a circuit

mx = m.int(ic = 0.5)
my = m.int(ic = 0.5)
mz = m.int(ic = 0.5)
xz = m.mul()
xy = m.mul()

m.connect(mx, xz.a)                     # Product -x * -z = xz
m.connect(mz, xz.b)

m.connect(mx, xy.a)                     # Product -x * -y = xy
m.connect(my, xy.b)

m.connect(my, mx, weight = -a)
m.connect(mx, mx, weight = a*0.8)       # 0.8 increases stability

m.connect(mx, my, weight = -b)
m.connect(xz, my, weight = -4.)
m.connect(my, my, weight = 0.1)

m.connect(xy, mz, weight = 4.)
m.connect(mz, mz, weight = c)

m.measure(mx, adc_channel=0)
m.measure(my, adc_channel=1)
m.measure(mz, adc_channel=2)


# send to LUCIDAC and retrieve results
op_secs = 0.1 # duration of a single OP cycle

luci = LUCIDAC("tcp://192.168.150.78:5732")
luci.set_circuit(m)
luci.set_daq(sample_rate=20_000)
luci.set_run(
  ic_time = 1000, 
  op_time=int(op_secs * 1_000_000_000),
  halt_on_overload=False,
  repetitive=True)
run = luci.run()

# receive data and concatenate over all cycles
data = []
cycles = 0
for ix, new_data in enumerate(run.next_data(mark_op_end_by_none=True)):
  if new_data is not None:
    data += new_data
  else:
    # if data is NONE, an OP cycle has been successfully ended
    print("<IP/OP CYCLE ENDED>")
    cycles += 1

    if cycles == num_cycles:
      break

# stop the run - from here on out, ignore all incoming messages
has_stopped = run.stop()

ax = plt.figure().add_subplot(projection='3d')
coordinates = np.array(data).T
print(coordinates.shape)
ax.plot(*coordinates, label="data")
ax.legend()
plt.show()
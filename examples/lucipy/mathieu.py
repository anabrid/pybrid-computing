from pybrid.lucipy import Circuit, LUCIDAC
import matplotlib.pyplot as plt
import numpy as np

op_secs = .05 # duration of OP cycle in seconds
sample_rate = 100_000

# These are the two parameters of Mathieu's equation which have to 
# be varied to get a stability map. 0 <= a <= 8 and 0 <= q <= 5.
a = 4
q = 1.8

# First we need an amplitude stabilised cosine signal. Since we do not have
# limiters at the moment, we use a van der Pol-oscillator for that purpose.
eta = .1                # A small value ensures good spectral cleanliness

m = Circuit()

mdy = m.int(slow=True)
y   = m.int(ic = -1, slow=True)
y2  = m.mul()
fb  = m.mul()
k   = m.const()

m.connect(fb, mdy, weight = -eta * 2)   # We need cos(2t), so all inputs 
m.connect(y,  mdy, weight = -0.5 * 2)   # to the integrators get a factor 2.

m.connect(mdy, y, weight = 2 * 2)

m.connect(y, y2.a)
m.connect(y, y2.b)

m.connect(y2,  fb.a, weight = -1)
m.connect(k,   fb.a, weight = 0.25)
m.connect(mdy, fb.b)

# Now for the actual Mathieu equation:
mdym = m.int()
ym   = m.int(ic = 0.1)
p    = m.mul()

m.connect(ym, mdym, weight = -a)
m.connect(p,  mdym, weight = q)

m.connect(mdym, ym)

m.connect(y, p.a)
m.connect(ym, p.b, weight = 2)


# c.probe(ym, front_port=0)

m.measure(ym, adc_channel=0)

luci = LUCIDAC()
luci.set_circuit(m)
luci.set_daq(num_channels=3, sample_rate=sample_rate)
luci.set_run(ic_time = 1_000, op_time=int(op_secs * 1_000_000_000))
run = luci.run()

def time_series(sample_rate, sample_count):
    sample_period_micros = 1_000_000 // sample_rate
    sample_period = sample_period_micros / 1_000_000
    real_sample_time = sample_period * (sample_count - 1)
    return np.linspace(0, real_sample_time, sample_count)

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
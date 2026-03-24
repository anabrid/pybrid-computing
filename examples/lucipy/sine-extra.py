# Copyright (c) 2022-2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later
from pybrid.lucipy import Circuit, LUCIDAC, time_series, WaveForm
import matplotlib.pyplot as plt
import numpy as np

###
# Create a simple sine/cosine oscillator circuit in lucipy-syntax with some
# additional goodies (LEDs, signal generator) showing the use of the pront panel.
#
# For this to work, please:
# - attach an oscilloscope to analog outputs A0, A1 and OP (trigger on OP)
# - connect the Rect signal to analog in 2, the sine signal to analog in 3
###

###
# Auto-detect LUCIDAC-device (empty constructor) or:
# - set environment variable LUCIDAC_ENDPOINT to a connection string
# - pass the connection string directly
#
# where the connection string is `tcp://<LUCIDAC IP or hostname>:5732`.
###
luci    = LUCIDAC()

c   = luci.create_circuit()             # Create a circuit

ic_sin  = -1                            # Initial value for the sine
omega   = .01 * (2.*np.pi)              # Oscillation frequency

sin = c.int(ic = ic_sin)                # Integrators for sine and cosine
cos = c.int()

port0 = c.output(0)                     # Allocate output MCX plugs
port1 = c.output(1)

c.connect(sin, cos, weight = +omega)    # Connect sine to cosine integrator
c.connect(cos, sin, weight = -omega)    # Connect cosine to sine integrator

c.probe(sin, adc_channel=0)             # Connect integrators to ADC
c.probe(cos, adc_channel=1)             # to sample data

c.connect(sin, port0)                   # Connect signals to analog output as
c.connect(cos, port1)                   # well

# wire inputs through ID-paths in order to sample from them
input2 = c.input(2)
input3 = c.input(3)

mul0 = c.mul()

c.connect(input2, mul0.a)
c.connect(input3, mul0.b)

c.probe(mul0.a.id(), adc_channel=2)
c.probe(mul0.b.id(), adc_channel=3)

###
# Setup the front panel:
# - signal generator
###
sg = c.signal_generator()
sg.wave_form = WaveForm.SINE_AND_SQUARE
sg.frequency = 1000
sg.amplitude = 0.6
sg.offset = 0.2
sg.square_voltage_low = -0.2
sg.square_voltage_high = 0.7
sg.dac_outputs = [0.3, -0.8]
sg.sleep = False

# Set LEDs (list of booleans)
c.set_leds([True, True, False, True, False, True, True, True])

###
# Settings for sampling and circuit execution
###
op_secs     = .1                       # Duration of OP cycle in seconds
sample_rate = 100_000                   # Samples per second (max: 150_000 for each channel)

luci.set_daq(num_channels=2, sample_rate=sample_rate)
luci.set_run(ic_time = 1_000, op_time=int(op_secs * 1_000_000_000))

###
# Run circuit and start sampling
###
run = luci.run()

###
# Receive sample data and plot
###
for ix, values in enumerate(run.data):
    x = time_series(sample_rate, len(values))
    plt.plot(x, values, label=f"Probe {ix}")
plt.xlabel("time / s")
plt.legend()
plt.grid()
plt.show()
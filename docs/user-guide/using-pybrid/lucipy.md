# Lucipy syntax

The original release of the LUCIDAC came with the
[lucipy client](https://github.com/anabrid/lucipy), whose
[documentation](https://anabrid.dev/docs/lucipy/dirhtml/) is still online.
Since then, both the firmware and the messaging protocol have undergone
breaking changes (the wire format moved from JSON to protobuf), so the
standalone `lucipy` package no longer talks to current devices. The latest
LUCIDAC firmware lives at
[lucidac-resources](https://github.com/anabrid/lucidac-resources). To
preserve the convenience of the old syntax, `pybrid` now ships its own
equivalent under `pybrid.lucipy`, which is a thin wrapper on top of the
underlying `pybrid` classes. We generally recommend it as the simplest way
to interact with a LUCIDAC.

The main entry point is `pybrid.lucipy.Circuit`, which lets us describe
circuits in the familiar lucipy notation. Once a circuit has been built,
the `run()` method on the `LUCIDAC` wrapper opens a session, executes the
circuit exactly once, and returns the captured measurements as a list under
`run.data`. The example below builds a sine/cosine oscillator on two
integrators, wires them up so that each one drives the other with the
desired frequency, probes both onto ADC channels and runs the computation:

```python
from pybrid.lucipy import Circuit, LUCIDAC, time_series

# ... further imports ...

# Auto-detect LUCIDAC-device (empty constructor) or:
# - set environment variable LUCIDAC_ENDPOINT to a connection string
# - pass the connection string directly
#
# where the connection string is `tcp://<LUCIDAC IP or hostname>:5732`.
luci    = LUCIDAC()

c   = luci.create_circuit()             # Create a circuit

ic_sin  = -1                            # Initial value for the sine
omega   = .01 * (2.*np.pi)              # Oscillation frequency

sin = c.int(ic = ic_sin)                # Integrators for sine and cosine
cos = c.int()

c.connect(sin, cos, weight = +omega)    # Connect sine to cosine integrator
c.connect(cos, sin, weight = -omega)    # Connect cosine to sine integrator

c.probe(sin, adc_channel=0)             # Connect integrators to ADC
c.probe(cos, adc_channel=1)             # to sample data

# Settings for sampling and circuit execution
op_secs     = .05                       # Duration of OP cycle in seconds
sample_rate = 100_000                   # Samples per second (device caps ~500k total, split across channels)

luci.set_daq(num_channels=2, sample_rate=sample_rate)
luci.set_run(ic_time = 1_000, op_time=int(op_secs * 1_000_000_000))

# Run circuit and start sampling
run = luci.run()

# ... evaluate run.data and plot results ...
```

## Interaction with `pybrid`

We can drop down into the underlying `pybrid` machinery at any point.
The `LUCIDAC` class exposes a `controller()` method that returns the
underlying `Controller` from the `pybrid.lucidac` package, which in turn
gives raw access to the `Computer` object via `controller().computer`.
This is useful whenever we need to read or modify entities (such as the
front panel, calibration data or individual blocks) that the lucipy DSL
does not cover directly.

A `Circuit` built with lucipy can also be exported into a protobuf payload
suitable for the
[wire protocol](../../developer-guide/data-and-messaging-protocol.md).
Calling `to_config()` runs the circuit through the `LUCIDACSerializer` and
returns a `pb.File` (the same on-disk envelope described on the
[file formats](./file-formats.md) page). The inner `pb.Module` is reachable
via the `.module` attribute:

```python
from pybrid.lucipy import Circuit, LUCIDAC

luci = LUCIDAC()
c = luci.create_circuit()

# ... configure the circuit ...

# Serialize to a protobuf File (which wraps a pb.Module) ...
pb_file = c.to_config()

# ... and access the underlying pb.Module
module = pb_file.module
```

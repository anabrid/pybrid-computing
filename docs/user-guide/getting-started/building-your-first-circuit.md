# Building Your First Circuit

!!! info

    This tutorial uses the low-level `pybrid`-syntax which is compatible
    with all supported devices; for LUCIDACs, there is the higher-level
    [lucipy](../using-pybrid/lucipy.md) syntax especially good for
    beginners.

Before starting on a simple circuit, you will need to set up `pybrid` and
to find out the IP address of your device. Throughout this document we are
assuming a LUCIDAC reachable at `192.168.1.2`. The circuit we are about to
build models a _harmonic oscillator_, governed by the ODE
$\frac{d^2}{dt^2}h(t) = -h(t)$ with $h(0) = 0.42$, and we will be capturing
both $h(t)$ and $\dot{h}(t) = \frac{d}{dt}h$ via the analog-to-digital
converters (ADCs) on the device. To understand _why_ we configure the
computer the way we do, please read the dedicated sections in the
[architecture guide](../../hardware-architecture/index.md).

(TBD: graphic for the circuit)

## Setting up the script

We start by importing the relevant classes from `pybrid`. The example uses
the LUCIDAC controller, but the same code translates to an mREDAC by
swapping the import for `from pybrid.redac.controller import Controller`:

```python
import asyncio
from matplotlib import pyplot as plt
import numpy as np

from pybrid.lucidac.controller import Controller
from pybrid.redac import DAQConfig, RunConfig
```

`pybrid` uses Python's [async](https://docs.python.org/3/library/asyncio.html)
machinery throughout to hide network latencies and I/O, so the rest of the
example lives inside an `async` function:

```python
async def main():
    ...

asyncio.run(main())
```

With that scaffolding in place, we are ready to configure the LUCIDAC.
Before we touch any code, here are the two abstractions to keep in mind.
A `Controller` is the client class for analog devices: it connects to
hardware, builds the entity object model from what the device reports, and
handles all communication with the device (see the
[protocol](../../developer-guide/data-and-messaging-protocol.md) for
details). The _entity object model_ is the in-memory representation of
those hardware components in pure Python; it is created at connect time
through automatic _deserialization_ of the device's _hardware
specification_, and is then configured by the user to realize a circuit
before being _serialized_ by the controller and transmitted as the
_hardware configuration_. In short: a _specification_ describes _what_
hardware the analog device has, and a _configuration_ describes how its
coefficients, switches and so on are set.

The most common usage pattern is the "configure-run-evaluate" loop. The
controller connects to the device and downloads its specification, which
is a hierarchical description of its hardware structure (see the
[hierarchy](../../hardware-architecture/hierarchy-from-cluster-to-the-redac.md)
page). From that specification, `pybrid` generates the entity object model
(the "computer"). The user then configures the computer in memory to
realize a particular analog circuit. The computer's configuration is
serialized into a protocol message and sent to the device, which runs
auto-calibration and finally executes the circuit. While the circuit
runs, the device streams the captured samples back over the network, and
`pybrid` collects them into a consolidated list of channels in Python.

## Connecting to the device

The first step in our example is to instantiate a controller, have it
connect to the device and reach into the entity object model:

```python
async with Controller() as controller:

    # connect to LUCIDAC
    await controller.add_device(
        "192.168.1.2",
        5732
    )

    # retrieve the entity object model for the LUCIDAC (i.e. "cluster")
    computer = controller.computer
    carrier = computer.carriers[0]
    cluster = carrier.clusters[0]
```

The REDAC family has a hierarchical structure (again, see the
[hierarchy](../../hardware-architecture/hierarchy-from-cluster-to-the-redac.md)
page) with carriers (mREDACs) as the smallest individually operable units.
The LUCIDAC is somewhat special: it is roughly equivalent to a single
_cluster_ rather than to a full carrier, so in `pybrid` we model it as a
carrier with exactly one cluster, and we configure the device by
configuring that cluster.

## Configuring the cluster

With the `cluster` reference in hand we can start configuring its blocks.
The order matters: we work outwards from the M-block, then route signals
through the U-block, weight them with the C-block, and finally close the
loop with the I-block. Use your IDE or IntelliSense to explore the
`cluster` object and its members as you go.

### M-block: integrators and initial conditions

As shown in [its architecture](../../hardware-architecture/list-of-blocks.md),
each cluster has two slots for M-blocks (M0 and M1). While they are
exchangeable, the M0 slot in most cases contains an MInt block with eight
integrators, where each integrator $i$ is wired to input $i$ and output
$i$. Our ODE has $\ddot{h}$ as its highest-order derivative, so we need
two integrators: integrator 0 will integrate $\dot{h}(t)$ to $h(t)$, and
integrator 1 will integrate $\ddot{h}(t)$ to $\dot{h}(t)$. Integrators have
two properties we can set. The first, `k_0`, is the acceleration factor
(default 10,000), which makes the system run 10,000 times faster than
real time. The second, `ic`, is the initial condition. In this example we
leave $k_0$ at its default and only set the initial condition:

```python
cluster.m0block.elements[0].ic = 0.42
cluster.m0block.elements[1].ic = 0  # 0 by default
```

### U-block: fan-out routing

In the C-block, almost all lanes are interchangeable (with the exception
of analog I/O), so we are free to choose which integrator output sits on
which lane. For simplicity we put integrator 0's output on lane 0 and
integrator 1's output on lane 1:

```python
cluster.ublock.outputs[0] = 0
cluster.ublock.outputs[1] = 1
```

The U-block works by _fan-out_: for every output of the M-blocks, you can
route the signal to multiple lanes in the C-block. The U-block also
contains a _constant giver_, capable of producing the constants
$\{0.1, 1\}$, but we do not need it in this example.

### C-block: coefficients

The C-block has one reconfigurable coefficient per lane, with each
coefficient living in the range $[-1.0, 1.0]$. Together with the I-block's
_upscaling_ feature (described below), the effective range becomes
$[-8.0, 8.0]$. According to our circuit diagram we need to weigh integrator
0's signal (lane 0) with $-1.0$ and integrator 1's signal (lane 1) with
$1.0$:

```python
cluster.cblock.elements[0].factor = -1.0
cluster.cblock.elements[1].factor = 1.0
```

### I-block: closing the loop

All that is left now is to close the loop by feeding the signal on lane 0
back into integrator 1 and the signal on lane 1 back into integrator 0.
The I-block works by implicit summation in a _fan-in_ mode: for each
output of the I-block (which is an input of the M-block), we assign a
set of C-block lanes to be summed. The I-block can also _upscale_ signals
on individual lanes by a factor of 8, but we do not need that here:

```python
cluster.iblock.outputs[0] = {1}
cluster.iblock.outputs[1] = {0}
```

### Capturing the integrator outputs

The ADCs on LUCIDAC and REDAC devices are wired to M-block outputs. To
capture the two integrator outputs we are interested in, we use the
convenience function on the computer's DAQ object:

```python
computer.daq.capture(
    cluster.m0block.elements[0],
    cluster.m0block.elements[1])
```

At this point the entity object model fully describes our ODE as a
circuit. What is left is to configure the _execution_ of that circuit and
hand it to the device.

## Running the circuit

We control execution through a `Session` object, which we obtain from
the controller so that it is wired up correctly (it carries a reference
to the controller, among other things):

```python
session = controller.create_session()
```

All commands issued on a session use _deferred execution_: they are
queued in the order they are added and only run when we finally call
`execute()`. Before that, we configure how long the device should
integrate and at what rate it should sample. The mode in which the
analog computer actively integrates is called "OP", and the OP duration
is set ahead of time with nanosecond precision:

```python
run_config = RunConfig(op_time=2_560_000)
```

We also need to pick a sample rate, in samples per second. Note that
the LUCIDAC's HybridController caps the total sampling rate at roughly
500 kHz divided across all captured signals. Since we are capturing
two signals, we have around 250,000 samples per channel per second to
play with; for this example we use 100,000:

```python
daq_config = DAQConfig(sample_rate=100_000)
```

Thanks to the chaining syntax, a typical session can be assembled and
fired off in a single sequence:

```python
runs = await (
        session
        .set_config(computer)  # serialize and send configuration
        .calibrate(gain=True, offset=True)
        .run(run_config, daq_config)
        .execute()  # execute all of the former commands
    )
```

Multiple `run()` commands inside the same session would result in
multiple entries in the `runs` list. Since we only have one run, we
pick the first entry with `run = runs[0]`.

## Plotting the results

To round things off we use `matplotlib` to plot the captured data:

```python
for channel in run.data:
    if channel is not None:
        plt.plot(np.array(channel).flatten())
plt.ylabel("Amplitude x")
plt.xlabel("'Time' t")
plt.show()
```

That's it, you just ran your first circuit on your device. Note that the
approach we are taking here, defining block routing by hand, is much like
assembly programming on digital systems. In most cases users can use
anabrid's `redacc` compiler to automate the transformation from ODE to
circuit.

# Programmatically

`pybrid` is distributed as two installable packages that both share the
top-level `pybrid` namespace: the pure-Python `pybrid-computing` package, which
contains the public API that user code interacts with, and the C++ extension
`pybrid-computing-native`, which is a required dependency of `pybrid-computing`
and is pulled in automatically during installation. The native extension is
used internally and rarely touched by user code directly. For a deeper look at
the individual classes, refer to the [developer guide](../../developer-guide/index.md).

## Main packages

### Abstractions and device backends

At the core of `pybrid-computing` sits the `pybrid.base.hybrid` subpackage,
which defines the abstract base classes that every device backend inherits
from. The classes a user is most likely to encounter are:

- `Computer` is the Python model of a device and represents it as a hierarchy
of _entities_. The term "computer" is used throughout this documentation as an
umbrella term for LUCIDAC- and REDAC-class devices.
- `Controller` is the central primitive to interact with a device. It manages
the connections to the hardware, implements the communication protocol and
initializes the entity object model (`Computer`) from the specification it
receives upon connecting.
- `Run` is the data structure carrying all information about a single execution
(IC/OP) cycle of a circuit, including its status and the captured measurements.
- `Serializer` and its counterpart deserializer translate a `Computer` object to
and from the [protobuf](../../developer-guide/data-and-messaging-protocol.md)
binary format that is both sent over the wire and stored on disk (see also
[file formats](./file-formats.md)).
- `Entity` is the common base class for every configurable hardware component.
Entities are hierarchical (each has a list of `children`) and addressable via
a `/`-separated path beginning with its carrier's MAC address, e.g.
`AA-BB-CC-DD-EE-FF/0/M0` refers to the M0 block of cluster 0 on the carrier with
MAC `AA-BB-CC-DD-EE-FF`.

Each supported device has its own subpackage that concretises the abstractions
above. Internally, `pybrid.redac` is the canonical implementation and the other
device backends inherit from it, abstracting away device-specific peculiarities:

- `pybrid.redac` provides the REDAC `Controller`, `Session` and `Run` objects
that every other device backend builds upon. Alongside, it ships the block-level
models under `pybrid.redac.blocks` (`MIntBlock`, `MMulBlock`, `UBlock`,
`CBlock`, `IBlock`, `SHBlock`, `TBlock`), the serializer and deserializer
under `pybrid.redac.protocol`, proxy-mode support under `pybrid.redac.proxy`
(see [proxy details](./proxy.md)) and zeroconf-based device auto-detection via
`pybrid.redac.detect`.
- `pybrid.lucidac` is a thin specialisation of `pybrid.redac` for the LUCIDAC,
which is modelled as a single-carrier REDAC with one cluster. It adds the
LUCIDAC-specific `FrontPanel` and `FrontPlane` entities that expose the LED
indicators and the ACL analog I/O.
- `pybrid.sim` is the device backend for the `pybrid` simulator and is useful
for running circuits without a physical device attached.
- `pybrid.lucipy` is a thin wrapper on top of `pybrid.lucidac` that reproduces
the notation of the original `lucipy` client for the simple configuration of
LUCIDACs and their circuits. See the [lucipy syntax](./lucipy.md) page for
details.

### Protocol, file I/O and shared utilities

The remaining modules under `pybrid.base` provide device-agnostic building
blocks that all device layers rely on:

- `pybrid.base.proto` bundles the protobuf bindings and file I/O helpers. It
exposes the auto-generated message classes (`main_pb2.File`, `Module`, `Item`,
...), the `ProtoIO` helper for loading and storing `Module`s as `.apb` binary
files, and `ProtoVersioning`, which tracks the current schema version used when
writing new files.
- `pybrid.base.analog` contains device-agnostic analog primitives, most notably
the `computations` module that describes analog computation elements such as
`Integration`, `Multiplication`, `Summation`, `SquareRoot` and `Identity`.
- `pybrid.base.utils` holds shared utilities used throughout the stack:
`Path` addressing for entities, descriptor helpers, logging configuration and
dynamic imports.

### CLI, mock server and developer helpers

Alongside the library code, `pybrid-computing` ships a few packages that make
day-to-day development easier:

- `pybrid.cli` is the `pybrid` command-line entrypoint built on `asyncclick`
and provides the `dummy`, `lucidac`, `redac` and `sim` subcommands. See
[Using the CLI](./using-the-cli.md) for details.
- `pybrid.mock` offers an in-process mock server (`DummyDAC`) that emulates a
LUCIDAC over TCP for testing and offline development. Its behaviour is
configurable via `DummyDACConfig`, including error-injection hooks
(`DummyDACErrorStage`) that are useful for exercising error paths in client
code.
- `pybrid.util` contains general-purpose helpers that are not tied to a
specific device, such as progress reporting.

### Native extension: `pybrid-computing-native`

`pybrid-computing-native` provides a low-level C++ implementation of the
networking stack and the proxy infrastructure (see
[proxy details](./proxy.md)) that `pybrid-computing` uses internally. It is
declared as a required dependency and is installed automatically alongside
`pybrid-computing`, so there is nothing to set up manually, and user code will
normally not import from it directly.


## Code idioms

Since `pybrid` is open source, we invite users and developers to use their IDEs
and/or coding agents to view the documentation of classes mentioned above. However,
it is generally helpful to see some of the "idioms", i.e. reuseable code blocks
and patterns for `pybrid` usage. Some of those idioms are shown in the remainder of this
section.

### Establish a connection with a controller

The controller is the main entry point: instantiate it, register one or more
devices via `add_device(host, port)`, and use it as an async context manager so
that connections are properly closed when you are done. After entering the
context, calling `controller.reset()` puts the device into a known state.

For a single LUCIDAC, use the LUCIDAC-specific controller:
```python
from pybrid.lucidac.controller import Controller as LUCIDACController

controller = LUCIDACController()
await controller.add_device("192.168.1.100", 5732)

async with controller:
    await controller.reset()
    # ... interact with the device ...
```

For multiple LUCIDACs, simply call `add_device()` multiple times; the
controller's computer model will then expose all of them as carriers. Note
that, in order to operate multiple LUCIDACs synchronously, they must be wired
together via a flatband cable as described in the LUCIDAC manual:
```python
from pybrid.lucidac.controller import Controller as LUCIDACController

controller = LUCIDACController()
await controller.add_device("192.168.1.100", 5732)
await controller.add_device("192.168.1.101", 5732)

async with controller:
    await controller.reset()
```

For an mREDAC/iREDAC (single endpoint, possibly fronting many carriers in
proxy mode), use the REDAC controller instead:
```python
from pybrid.redac.controller import Controller as REDACController

controller = REDACController()
await controller.add_device("192.168.1.100", 5732)

async with controller:
    await controller.reset()
```

### Get the entity object model after connecting

Once a controller is connected, its `computer` attribute exposes the device's
entity hierarchy. You can drill down into carriers, clusters and individual
blocks (M, U, C, I, ...) and access (or modify) their elements directly:
```python
async with controller:
    computer = controller.computer

    for carrier in computer.carriers:
        for cluster in carrier.clusters:
            mblock = cluster.m0block
            for element in mblock.elements:
                print(element)
```

### Retrieve a device specification and store it in an `.apb` file

`controller.extract()` returns a cached `pb.Module` containing the hardware
specification (the entity hierarchy reported by the device). Pass this module to
`ProtoIO.store_module()` to persist it as an `.apb` file that can later be
loaded by, e.g., the simulator:
```python
from pybrid.base.proto.io import ProtoIO

async with controller:
    module = await controller.extract()
    ProtoIO.store_module(module, "device_spec.apb")
```

### Create a session that runs a configured circuit

Configuration changes made on the in-memory `computer` object are not
yet visible to the hardware. They become effective only once they are
wrapped into a `Session` and that session is executed. Sessions exist
for two reasons: **deferred execution**, so that a
configure/calibrate/run chain is sent to the device as a single
coherent pipeline rather than step by step, and **mutual exclusion**,
so that two coroutines sharing a controller cannot interleave their
traffic on the wire.

A session is a single-use pipeline. You obtain one from
`controller.create_session()`, append commands to it via a set of
chainable builder methods, and fire the whole thing off with
`execute()`. The builder methods you will reach for most often are:

- `set_config(computer)` / `set_module(module)`: enqueue a
  configuration write, either from the current in-memory `computer`
  object or from a previously loaded `.apb` module.
- `calibrate(...)`: enqueue a calibration pass over the analog core
  before the run executes. The default arguments cover the gain and
  offset calibrations users want most of the time.
- `run(config, daq=...)`: enqueue the actual execution, parameterised
  by `RunConfig` (phase durations) and `DAQConfig` (which channels at
  which rate). A session can contain several `run()` calls in a row
  if you want to execute several computations back-to-back without
  reconfiguring in between.
- `set_firmware(path)`: stage an OTA firmware update. The CLI
  [`update` command](./using-the-cli.md#prefix-update-ota-firmware-update)
  is a thin wrapper around this operation. This causes a disconnect when the
  device reboots and is _not_ recommended to be used with the other commands.

`execute()` awaits until every buffered step has returned and gives
back a `list[Run]` with one entry per `run()` call, in order. A
session instance cannot be executed twice; create a fresh session for
the next pipeline. While `execute()` is in flight, the controller's
internal session lock is held, so any other coroutine trying to open
a session against the same controller is suspended until the current
pipeline finishes.

The canonical pattern is therefore:

```python
from pybrid.redac import RunConfig, DAQConfig

async with controller:
    computer = controller.computer

    # ... modify entities on `computer` to build the circuit ...

    run_config = RunConfig(op_time=2_560_000)
    daq_config = DAQConfig(num_channels=2, sample_rate=100_000)

    session = controller.create_session()
    runs = await (
        session
        .set_config(computer)
        .calibrate(gain=True, offset=True)
        .run(run_config, daq=daq_config)
        .execute()
    )
    run = runs[0]
    for channel in run.data:
        ...  # process samples
```

### Interpret the lifecycle of a run

A `Run` tracks a single execution on the analog computer as it moves
through a small state machine. Understanding the states is useful
both when interpreting `run.state` after `execute()` returns and when
reading live updates off an attached debugger or log. The happy path
is:

```
NEW → QUEUED → TAKE_OFF → IC → OP → OP_END → DONE
```

The first three states cover bookkeeping: `NEW` is the freshly created
run object, `QUEUED` describes a run that is sitting in the session
pipeline, and `TAKE_OFF` is the brief preparation phase between "the
device accepted the run" and "the analog core is actually doing
something." The interesting states from a circuit-design perspective
are:

- **`IC` (initial condition).** The analog core loads each
  integrator's `.ic` value onto its capacitor. Nothing else happens
  yet and no integration is taking place. The IC phase has a
  configurable duration (`RunConfig.ic_time`, in nanoseconds).
- **`OP` (operating).** This is the phase during which the analog
  computer actually integrates: signals flow, feedback loops close,
  and the DAQ captures samples at the configured rate. The OP phase
  has a configurable duration (`RunConfig.op_time`, in nanoseconds)
  and ends automatically when that duration elapses.
- **`OP_END`.** A short finalisation phase after `OP` that flushes
  any remaining samples. `DAQConfig.sample_op_end` controls whether
  samples captured during this phase are kept.

A run can also land in two non-happy states:

- **`ERROR`**: something went wrong. Inspect `run.overloaded` for a
  list of elements that saturated during integration, and consult
  the controller's logs for the protocol-level reason.
- **`TMP_HALT`**: the device was temporarily paused, either by an
  external halt trigger (signalled by `run.externally_halted`) or by
  an explicit halt command from the client, and can still be
  resumed.

`DONE` and `ERROR` are the two terminal states. The convenience
`run.state.is_done()` returns true exactly for those two, which is
the check to use when you want to be certain a run has stopped
moving. For the precise mapping between protobuf-level states and
Python-level states, refer to `pybrid.redac.run.RunState`.

### Serialize and store a configured computer object

To persist a fully configured computer (specification _and_ configuration of
all entities), ask the computer for its serializer class, instantiate it, and
serialize. The result is a `pb.Module` that can again be written via
`ProtoIO.store_module()`:
```python
from pybrid.base.proto.io import ProtoIO

computer = controller.computer

# ... configure entities on `computer` here (e.g. cluster.route(...),
#     mblock.elements[i].ic = ..., computer.daq.capture(...)) ...

serializer = computer.get_serializer()()
module = serializer.serialize(computer)

ProtoIO.store_module(module, "full_config.apb")
```

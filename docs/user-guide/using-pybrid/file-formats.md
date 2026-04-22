# File Formats

`pybrid` uses the "analog protobuf" format, a packed binary format based on
[Google's Protobuf](https://protobuf.dev/). The same `.proto` schema serves
two purposes inside the project: it defines the messages exchanged between
clients and devices over the wire, and it defines the payload formats used
when device data is serialized to disk. Whenever we write analog-protobuf
data to disk, we use the `.apb` extension. For a primer on protobuf and the
full wire protocol, refer to the
[developer guide](../../developer-guide/data-and-messaging-protocol.md);
this page only covers the subset that users need for storing and loading
device data.

For everyday use, only three message types matter: `File`, `Module` and
`Item`. All three are generated protobuf classes and live in the auto-built
module `pybrid.base.proto.main_pb2`. The convention used throughout the
`pybrid` codebase is to import that module under the short alias `pb` and
then to refer to the types as `pb.File`, `pb.Module`, `pb.Item` and so on:

```python
import pybrid.base.proto.main_pb2 as pb

module = pb.Module()  # an empty Module, ready to be populated with Items
```

`File` is the top-level on-disk envelope and carries a `Version` together
with a single `Module`. The version field is what allows older
`.apb` files to be upgraded transparently to the current schema when they
are loaded. Inside it, a `Module` is a flat container holding an ordered
list of `Item`s; the same `Module` shape is also what `pybrid` ships in a
`ConfigCommand` when configuring a device, so reading from disk and
configuring hardware are essentially the same operation. Each `Item`, in
turn, is a tagged union (a protobuf `oneof`) whose variants describe either
a piece of hardware or a configuration value for a piece of hardware.

The `Item` variants split cleanly into two groups. `EntitySpecification`
_specifies_ hardware: it stores the hierarchy of entities (carriers,
clusters, blocks, ...) reported by a device when we first connect to it,
and it is what makes a stored module portable, since the receiver can tell
exactly which hardware shape the configuration was written for. Every
other `Item` specialization (`MulConfig`, `CoefConfig`, `ClusterConfig`,
`FrontPanelConfig`, ...) instead _configures_ a single entity and carries
the `EntityId` (path) of the entity it applies to. A typical `Module` will
contain both kinds of items at once: one `EntitySpecification` per carrier
followed by the configuration items for all of its blocks.

The canonical way to read and write modules from disk is the helper class
`pybrid.base.proto.ProtoIO`. It only accepts the `.apb` extension and adds
two things on top of raw protobuf serialization. When we call
`store_module()`, it wraps our `Module` into a `File` and stamps it with
the current schema version before writing it out. When we call
`load_module()`, it parses the `File` from disk, runs it through
`ProtoVersioning` to upgrade older revisions to the current schema, and
then returns the inner `Module` to us. The `File` envelope only exists on
disk for versioning purposes and is unwrapped before the data ever reaches
user code.

As a first example, here is how we serialize the configuration of an
analog computer to an `.apb` file. We connect to a device, ask its
`Computer` object for its serializer class, instantiate it (the trailing
`()` after `get_serializer()` is what does the instantiation), and hand
the resulting `Module` to `ProtoIO.store_module()`. The controller is
entered as an async context manager so that the connection is cleaned up
once we are done.

```python
from pybrid.redac.controller import Controller as REDACController
from pybrid.base.proto.io import ProtoIO

controller = REDACController()
await controller.add_device("192.168.1.100", 5732)

async with controller:
    # ... optionally modify the computer's configuration in place ...

    computer = controller.computer
    serializer = computer.get_serializer()()
    module = serializer.serialize(computer)

    ProtoIO.store_module(module, "my_config.apb")
```

The reverse direction is just as common: we have an `.apb` file describing
some hardware and we want to spin up the simulator to mimic it. The
simulator needs an `EntitySpecification` to know which hardware shape to
emulate, and an `.apb` previously written by `ProtoIO.store_module()` (or
by the equivalent CLI command) is the standard way to provide it. We load
the file with `ProtoIO.load_module()` and pass the resulting `Module`
straight to `add_device()` via its `specification` argument.

```python
from pybrid.sim.controller import Controller as SimController
from pybrid.base.proto.io import ProtoIO

specification = ProtoIO.load_module("lucidac-spec.apb")

controller = SimController()
await controller.add_device(
    "localhost", 5732,
    specification=specification,
)
```

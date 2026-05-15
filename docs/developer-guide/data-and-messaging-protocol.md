# Data and Messaging Protocol

At its heart, clients and analog devices made by anabrid communicate via a
binary protocol based on [protobuf](https://protobuf.dev/). Protobuf is a
library that uses simple, structured text files (`.proto`) to define a binary
format. From this textual description, the protobuf compiler `protoc` generates
code that de/serializes this format from/to structures in different programming
languages. Within the `pybrid` project, we use protobuf both to define messages
exchanged between clients and analog devices ("communication") and as a way to
define payloads to some of these messages ("data").

## A short primer on Protobuf

This section gives a _very_ brief overview of protobuf for both users and
developers. Reading and understanding it is not strictly necessary for working
with `pybrid`, but it generally helps for more in-depth learning about analog
computers.

Protocol Buffers (protobuf) is Google's language-neutral, platform-neutral serialization format for structured data. Think of it as a stricter, more efficient JSON with compile-time schema validation.

### The Message

You define your data structure in a `.proto` file:

```protobuf
syntax = "proto3";

message User {
  string id = 1;
  string name = 2;
  repeated string tags = 3;
}
```

The compiler generates Python classes. You work with these classes, not the raw format:

```python
from myproto_pb2 import User

user = User(id="123", name="Alice", tags=["admin", "active"])
```

### Serialization

Protobuf serializes to binary, not text. It's compact and fast:

```python
# Serialize to bytes
data = user.SerializeToString()

# Deserialize from bytes
user2 = User()
user2.ParseFromString(data)
```

The binary format uses field numbers (not names) on the wire, making it:
- Smaller than JSON (no field names, efficient encoding)
- Faster to parse (no string parsing, direct field mapping)
- Schema-evolution friendly (add/remove fields by number)

### Storage and Messaging

Protobuf serves dual purposes:

**As storage:** Save serialized bytes to disk, database, or cache. The schema is your migration plan; new code can read old data if field numbers are preserved.

**As messaging:** Send serialized bytes over networks. The schema is your contract; both sides must agree on the `.proto` definition.

### TCP Communication

Sending protobuf over TCP requires length-prefixing; otherwise the receiver doesn't know where one message ends and the next begins.

```python
import socket
from myproto_pb2 import User

# SENDING
def send_protobuf(sock: socket.socket, msg: Message):
    data = msg.SerializeToString()
    # Prefix with 4-byte length (network byte order)
    sock.sendall(len(data).to_bytes(4, 'big') + data)

# RECEIVING
def recv_protobuf(sock: socket.socket, msg_class: type[Message]) -> Message:
    # Read length prefix first
    length_bytes = recv_exact(sock, 4)
    length = int.from_bytes(length_bytes, 'big')

    # Read the message
    data = recv_exact(sock, length)

    msg = msg_class()
    msg.ParseFromString(data)
    return msg

def recv_exact(sock: socket.socket, n: int) -> bytes:
    data = b''
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise ConnectionError("Connection closed")
        data += chunk
    return data
```

The length prefix is critical; without it, you can't stream multiple messages over a single TCP connection.

**Bottom line**: Protobuf gives you schema-enforced, efficient serialization.
Define once in `.proto`, compile to your language, and you're done. It is not
human-readable, but it is what you want when performance and size matter.

## Protobuf in pybrid

The communication protocol including its protobuf definition has been
open-sourced on [GitHub](https://github.com/anabrid/analog-protobuf) under a
permissive MIT licence. Within the repository, `main.proto` is the `.proto`
file containing the current version of anabrid's protobuf protocol ("analog
protobuf", short `apb`). The base `message` type for all messages exchanged
between analog device and client is `MessageV1`.

There are multiple classes of messages:

- `Commands`: messages sent from client to device. Devices never take
  initiative, i.e., they only respond to commands.
- `Response`: messages sent from device back to client in direct follow-up to a
  command (includes `SuccessMessage` and `ErrorMessage`).
- `Request`: much like a command, but coming from an unauthenticated source
  (applicable with the simulator). Unlike a command, a request can be denied
  (see, e.g., `UdpDataStreamingRefusedResponse`).
- `File`, `Module`, `Item`: storage formats for devices' specification and
  configuration. Items can also be payload to commands such as the
  `ConfigureCommand`.

With the generated protobuf files for Python, any type of `message` can be
serialized to a binary string and stored to a file. Independent of the type of
message serialized, we use the `.apb` extension to denote protobuf files
compatible with the analog protobuf format. The package `pybrid.base.proto`
contains the class `ProtoIO` which offers wrapper functions `load_module` and
`store_module` to store `Module` structures to disk. Modules can contain both
specifications and configurations for devices, which is why this is the
preferred way to serialize device data.

### Versioning

The protocol grows over time, and some changes might be breaking. A protobuf
`Version` is defined by three numbers (major, minor, and patch), and changes
in the major version usually break backwards compatibility. To deal with this,
`pybrid` ships a versioning facility in the `pybrid.base.proto` package: the
`ProtoVersioning` class offers an `update()` function that takes a `File`
object (essentially a `Module` with a `Version`) and iteratively updates it to
the newest version of the protocol, implementing one function per step from
version `i` to version `i + 1`. If updating is impossible automatically due to
breaking changes, an error is raised. When _storing_ a module using
`ProtoIO.store_module`, the version may be manually defined and defaults to
the current version (`ProtoVersioning.current()`).

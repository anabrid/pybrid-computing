# pybrid-computing

`pybrid-computing` (short: `pybrid`) is a Python library for configuring and
controlling [anabrid](https://anabrid.com/)'s LUCIDAC and REDAC analog-digital
hybrid computers. It serves as the runtime and "assembly"-level interface to
the hardware, talking to the device firmware over a protobuf-based wire
protocol via TCP/IP or USB Serial.

`pybrid` is one of the layers of the [LUCIstack](https://anabrid.github.io/lucistack/),
anabrid's end-to-end software stack for analog computing. Within the stack, it
owns the runtime and the wire protocol: everything below it is hardware and
firmware, everything above it (the `redacc` compiler, the `LUCIHUB` cloud
service) builds on top of `pybrid`.

## What you get

- An entity object model that mirrors the device structure (carriers,
  clusters, blocks, lanes), usable as the lowest programmable layer the
  hardware exposes.
- The reference implementation of the LUCIDAC/REDAC protobuf protocol, with
  `asyncio` and [pydantic](https://docs.pydantic.dev/) throughout.
- Device layers for LUCIDAC, REDAC, and the `redacc` simulator behind a single
  interface.
- A `pybrid` command-line tool with subcommands for device detection,
  configuration, runs, and a `dummy` mock server for hardware-free testing.
- An optional C++ companion (`pybrid-computing-native`) providing
  high-performance UDP/TCP networking and a proxy server for fronting multiple
  devices behind a single endpoint.

As a replacement for the deprecated `lucipy` syntx, the repo contains a high-level
`Circuit` API (`pybrid.lucipy`) for building computations without hand-wiring blocks.

## Installation

`pybrid` runs on Linux (x86/x64), Windows 10/11, and ARM-based macOS, on
Python 3.11 through 3.14. We recommend [uv](https://docs.astral.sh/uv/):

```bash
uv venv --python 3.13
uv pip install pybrid-computing
```

This pulls in the matching `pybrid-computing-native` wheel automatically. Plain
`pip install pybrid-computing` works too. See the
[setup guide](https://anabrid.github.io/pybrid-computing/user-guide/getting-started/setup/)
for installation from source and platforms without pre-built wheels.

## Documentation

Full documentation, including tutorials, the CLI reference, and the protocol
specification, lives at <https://anabrid.github.io/pybrid-computing/>.

## License

Written and maintained by [anabrid GmbH](https://anabrid.com/). Released as
open source under dual `MIT` / `GPL>=2` licensing.

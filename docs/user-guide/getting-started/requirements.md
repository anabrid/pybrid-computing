# Requirements

`pybrid` runs on Windows 10 and 11, on any Linux distribution for the
x86/x64 architecture, and on ARM-based Macs (M1 through M5) running
macOS. A Python installation is also required, with versions from 3.11
through 3.14 being supported.

The library itself is split into two installable components that
together make up a working `pybrid` setup:

- `pybrid-computing` is the pure-Python part and contains the entity
object model, the controller used for communication with the device,
and the messaging protocol.
- `pybrid-computing-native` is its compiled companion, providing
low-level, high-performance network handling that bypasses the
restrictions of Python's own I/O stack as well as the [proxy
functionality](../using-pybrid/proxy.md) for fronting one or more
devices behind a single endpoint.

Both packages are required for a working installation, and the
remainder of this guide assumes that both have been installed.

Because `pybrid-computing-native` is written in C++ for performance
reasons, it is distributed on PyPI as pre-built binary wheels for the
operating systems and architectures listed above. On any other
platform, the native extension must be compiled locally by following
the [developer's guide](../../developer-guide/index.md). Building from
source additionally requires a working installation of a modern C++
compiler supporting at least the C++14 standard, a recent version of
[cmake](https://cmake.org/), and the development headers for your
Python version.

# pybrid-computing

Python library for configuring and controlling anabrid's LUCIDAC/REDAC analog-digital hybrid computers.

Called `pybrid` (short for `pybrid-computing`), this library serves as both the runtime and the "assembly" level for hybrid analog computers. Pybrid is designed to be enough to interface with and operate anabrid's analog computers of the LUCIDAC and REDAC-lines on a low level, akin to assembly-level programming.

Note that `pybrid` is meant as a client to connect _directly_, via network (or proxy, see later) to the device. `pybrid` is **not** a cloud-like job scheduling system with sophisticated multi-user scheduling. The digital and administrative part of your analog computer is kept simple on purpose.

## Navigation

The documentation is organized into the following sections:

- **Overview** - Introduction to pybrid and its place in the software stack
- **User Guide** - In-depth guides for circuits, computations, and device management
- **Hardware Architecture** - Documentation of the REDAC hardware and block types
- **Developer Guide** - Technical documentation for contributors

## How to Get Started

The recommended reading path depends on your use case:

- **Everybody working with pybrid** should read the Overview first to understand the library's purpose and capabilities.

- **Users wanting to connect to an analog computer** should skip to the User Guide's Getting Started section for setup instructions, then follow one of the included examples to run their first computation.

- **Researchers developing low-level circuitry without a compiler** should study the Hardware Architecture after the Overview to understand the configurability of the hardware and see how configurations are built within the entity object model.

- **Developers** should focus on the Hardware Architecture first to understand the hardware structure, then proceed to study the protocol and communication schematics with the device. At that point, you will have enough basis to write alternative clients or extend pybrid for your needs.

## Supported Devices

`pybrid` currently has active support for two classes of hardware devices plus anabrid's proprietary `redacc` simulator:

- **[LUCIDAC](https://anabrid.com/lucidac)** devices are the smallest reconfigurable device in anabrid's lineup. They provide a compact, self-contained analog computing system.

- **[REDAC](https://anabrid.com/redac)** is a modular analog computer system built from carrier boards, each containing clusters of computational blocks. This architecture allows scaling from small to large analog computing setups.

- The **simulator** serves as a method of validation. Given a hardware specification
(see notes on architecture) it replicates device behaviour including a
very simplified error model on a mathematical level. By going through the compiler
and being able to simulate with _limits_, it is well suited for development of circuits.

## A Note on Openness

`pybrid`, including the contained protobuf-based data format and messaging protocol, is open source under a permissive license with extensive documentation offered as part of this project.
With the protocol being open, developers are able to implement client code in different languages and directly integrate LUCIDAC/REDAC devices in their end-user applications, bypassing the `pybrid` runtime when needed.

However, anabrid's current hardware, firmware and compiler is **not** open source.
Opening up the API of the device firmware is currently planned, but there is no ETA as of now.

!!! warning "LUCIDAC Firmware Compatibility"

    The LUCIDAC device was initially released with an [open-source firmware](https://github.com/anabrid/lucidac-firmware). While this firmware operates all functions of the LUCIDAC correctly and is fully functional, it is **not** compatible with the current version of `pybrid`. In case you base your developments on that firmware, please use the [lucipy](https://github.com/anabrid/lucipy) client code. Note that **both** these projects are not actively maintained by anabrid.

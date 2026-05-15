# User Guide

This section provides in-depth guides for using pybrid to design circuits, run computations, and manage devices from a user's perspective. If you are a developer wanting to modify or
extend pybrid, please refer to the [Developer section](../developer-guide/index.md).

Please note that programming with `pybrid` means low-level programming, compared
to assembly language for digital computers. On an analog computer, you are not moving
data in and out to/from registers, but you are connecting compute elements, coefficients
and input/output signals. Programming (or _configuring_) an analog computer
requires in-depth knowledge of the system's architecture.

After finishing the tutorials in this section and having set up your development
environment with `pybrid`, we recommend learning about the architecture
in [the architecture guide](../hardware-architecture/index.md).

`pybrid` serves multiple functions in anabrid's software stack. Besides a convenient
way to configure devices using Python, `pybrid` also serves as runtime environment
and collection of tools for device maintenance. For a list of functions, refer
to [the further usage guide](./using-pybrid/index.md).

## First steps

The [Getting Started](./getting-started/building-your-first-circuit.md) section takes users step-by-step through installing and setting up pybrid,
connecting to their device all the way to defining and running their first circuit.
Take this section as a "hands-on" tutorial - many concepts are being mentioned
and shown by example that are only explained later in both the
[hardware architecture](../hardware-architecture/index.md) and the
[developer's guide](../developer-guide/index.md).

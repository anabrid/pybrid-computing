# pybrid

`pybrid` is the Python library for configuring and controlling anabrid's LUCIDAC and REDAC analog-digital hybrid computers.

## Purpose and Scope

Pybrid serves as both the runtime environment and the "assembly" level programming interface for hybrid analog computers. It is designed to provide sufficient functionality to interface with and operate anabrid's analog computers on a low level, akin to assembly-level programming.

## Design Philosophy

Pybrid is meant as a direct client that connects to the device via network (TCP/IP) or USB Serial, with optional proxy mode for complex setups. It is explicitly **not** a cloud-like job scheduling system with sophisticated multi-user scheduling. The digital and administrative part of the analog computer is kept simple by design.

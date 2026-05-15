# Developer Guide

This section is meant for developers who want to _use_ `pybrid` within their
own projects and for contributors to anabrid's software stack. `pybrid` has
two main functions: constructing, serializing and deserializing the entity
object model for analog devices, and serving as the runtime layer that
handles communication, access control, and connection management for
connected analog devices. The developer docs split along those two lines into
the [entity object representation](./device-object-representation.md) on the
one hand, and the [data and messaging protocol](./data-and-messaging-protocol.md)
together with the [native networking code](./native-networking-code.md) on
the other. Coming from the architecture overview, especially from the
LUCIstack perspective, we recommend starting with the entity object model.

## On AI and agentic usage

As software developers and researchers, we live in wild times, with AI
agents becoming better every month. The broad access to frontier-level
intelligence also changes the value proposition of documentation like this:
instead of painstakingly including code and adding structured code
documentation, down to docstrings, it has become the norm to convey
_intent_, _architecture_ and _core guidelines_ in the documentation. Code
itself is closer to a "living organism", changing frequently and quickly
leading to out-of-sync documentation.

Following this idiom, this section of the documentation offers enough
information and overview to convey the guidelines and concepts governing the
development of `pybrid`, but leaves the links to the actual code and the
instructions on how to use it to agents. With the start of 2026, agents
have become **really good at search and synthesis** and are now mature
solutions for Q & A with middle-sized codebases such as this. We recommend
pointing your agent at the `docs/` folder first, especially the developer
documentation, or bootstrapping it from the `AGENTS.md` file (rename to
`CLAUDE.md` if you are a Claude Code user).

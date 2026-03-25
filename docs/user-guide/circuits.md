# Circuits

The `Circuit` class is the primary interface for designing analog computations.

## Creating a circuit

Every circuit is bound to a specific device by its MAC address:

```python
from pybrid.lucipy import Circuit

circuit = Circuit(mac="04-E9-E5-00-00-01")
```

## Allocating elements

Elements are allocated greedily across 32 lanes (0-31). Lanes 24-31 are shared with ACL I/O.

```python
integrator = circuit.Integrator()
multiplier = circuit.Multiplier()
identity = circuit.Identity()
const = circuit.Constant(0.5)
```

## Connecting elements

Use `circuit.connect()` to wire element outputs to inputs:

```python
circuit.connect(const, integrator)
circuit.connect(integrator, multiplier.a)
circuit.connect(const, multiplier.b)
```

Multipliers have two inputs accessible via `.a` and `.b`.

## Validation

Circuits are validated before being committed to a device. Validation checks for unconnected ports, lane conflicts, and resource exhaustion.

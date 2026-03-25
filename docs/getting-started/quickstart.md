# Quick Start

This guide walks through a minimal example: a simple integrator circuit on a LUCIDAC.

## Connect to a device

Set the endpoint via environment variable or pass it directly:

```bash
export LUCIDAC_ENDPOINT=tcp://192.168.1.100:5732
```

## Define a circuit

```python
from pybrid.lucipy import Circuit, LUCIStack

mac = "04-E9-E5-00-00-01"
circuit = Circuit(mac=mac)

# Allocate an integrator and a constant
integrator = circuit.Integrator()
const = circuit.Constant(0.5)

# Wire constant output into integrator input
circuit.connect(const, integrator)
```

## Run the computation

```python
import asyncio

async def main():
    stack = LUCIStack()
    async with stack:
        await stack.set_circuit(circuit)
        data = await stack.run()
        print(data)

asyncio.run(main())
```

## Development without hardware

Start the built-in mock server for local testing:

```bash
uv run pybrid dummy --host 0.0.0.0 --port 5732
```

Then point your code at `tcp://localhost:5732`.

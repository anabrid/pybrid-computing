# Running Computations

Once a circuit is defined, use `LUCIStack` to configure hardware and execute runs.

## Single device

```python
import asyncio
from pybrid.lucipy import Circuit, LUCIStack

async def main():
    circuit = Circuit(mac="04-E9-E5-00-00-01")
    integrator = circuit.Integrator()
    const = circuit.Constant(1.0)
    circuit.connect(const, integrator)

    stack = LUCIStack()
    async with stack:
        await stack.set_circuit(circuit)
        data = await stack.run()
        print(data)

asyncio.run(main())
```

## Multi-device (proxy mode)

When multiple carriers sit behind a single endpoint (proxy mode), `LUCIStack` discovers them automatically:

```python
async def main():
    stack = LUCIStack(endpoint="tcp://proxy-host:5732", standalone=False)
    async with stack:
        # stack.devices lists all discovered carriers
        for mac in stack.devices:
            print(f"Found device: {mac}")
```

## Run configuration

The `run()` method accepts parameters to control execution timing, sampling, and repetition. Refer to the API reference for full details.

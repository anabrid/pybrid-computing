# pybrid-computing: The python hybrid computing code

*pybrid* is a code that provides an interface to configure and control analog computers,
in particular the network-enabled LUCIDAC/REDAC analog-digital hybrid computers made by
[anabrid](https://anabrid.com/). The abstractions can be used by means of

* a fully [asyncio](https://docs.python.org/3/library/asyncio.html) library
* a framework (users providing callbacks in a clean class structure, however giving
  up most of the program flow control) called *Read-Eval-Configure-Loop* (RECL)
* a command line interface using [click](https://click.palletsprojects.com)

This python library provides the reference implementation for the LUCIDAC/REDAC
communication protocol (a simple ASCII yet fully asynchronous RPC message passing protocol
ontop of JSONL) by means of [pydantic](https://docs.pydantic.dev/latest/) data type modeling.
In particular, it is the reference implementation of a client communicating with a
[LUCIDAC hybrid controller MCU](https://anabrid.dev/docs/hybrid-controller/) via
USB Serial or TCP/IP.

The code is successfully used on modern day GNU/Linux, Mac OS X and MS Windows.

This code is written and maintained by [anabrid GmbH](https://anabrid.com/). It is released
as open source (dual licensed as `MIT` and `GPL>=2`).

## Installation

We recommend using [uv](https://docs.astral.sh/uv/) as the package manager for pybrid.

```bash
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install pybrid-computing
uv pip install pybrid-computing
```

Alternatively, you can use pip directly:

```bash
pip install pybrid-computing
```

Installation makes a command line executable `pybrid` available on your shell:

```
% pybrid --help
Usage: pybrid [OPTIONS] COMMAND [ARGS]...

  Entrypoint for all functions in the pybrid command line tool.

  Additional :code:`pybrid-computing` packages hook new subcommands into this
  entrypoint. Please see their documentation for additional available
  commands.

Options:
  --log-level [CRITICAL|ERROR|WARNING|INFO|DEBUG]
                                  Set all 'pybrid' loggers to the passed
                                  level.
  --help                          Show this message and exit.

Commands:
  detect   Detect devices in local network.
  dummy    Start a DummyDAC mock server for testing purposes.
  lucidac  Entrypoint for all LUCIDAC commands.
  redac    Entrypoint for all REDAC commands.
  sim      Entrypoint for all commands interacting with the simulator.
```

The `redac`, `lucidac`, and `sim` commands share the same subcommands for interacting
with the respective device types:

```
% pybrid redac --help
Usage: pybrid redac [OPTIONS] COMMAND [ARGS]...

  Entrypoint for all REDAC commands.

  Use :code:`pybrid redac --help` to list all available sub-commands.

Options:
  -h, --host TEXT                 Network name or address of the REDAC. Or
                                  address range to use for auto-detection.
  -p, --port INTEGER              Network port of the REDAC.
  --reset / --no-reset            Whether to reset the REDAC after connecting.
                                  [default: reset]
  --fake                          Whether to fake any communication, allowing
                                  you to run without any computer present.
  --standalone / --no-standalone  Run in standalone mode, which does not
                                  require an external super-controller or SYNC
                                  generator.  [default: no-standalone]
  --help                          Show this message and exit.

Commands:
  add-constant             Inject a constant and add it to the math block...
  convert                  Convert a JSON-pb file from an old, nested...
  display                  Display the hardware structure of the computer.
  get-entity-config        Get the configuration of an entity.
  get-entity-status        Get the status of an entity.
  get-system-temperatures
  hack                     Collects 'hack' commands, for development...
  monitor
  power-up                 Automate the current hack-power-up sequence,...
  proxy
  reset                    Reset the computer to initial configuration.
  route                    Route a signal on one cluster from one output...
  run                      Start a run (computation) and wait until it is...
  set-alias                Define an alias for a path in an interactive...
  set-connection           Set one or multiple connections in a U-Block...
  set-daq                  Configure data acquisition of subsequent run...
  set-element-config       Set one ATTRIBUTE to VALUE of the...
  shell                    Start an interactive shell and/or execute a...
  user-program
```

For testing without hardware, use the `dummy` command to start a mock server:

```
% pybrid dummy --help
Usage: pybrid dummy [OPTIONS]

  Start a DummyDAC mock server for testing purposes.

  The DummyDAC simulates REDAC hardware and can be used for testing without
  physical hardware. It responds to the same protocol as real hardware.

  Example usage:

      pybrid dummy -h 0.0.0.0 -p 5732     pybrid dummy --physical  # Use
      random MAC addresses

Options:
  -h, --host TEXT         Host address to bind the DummyDAC server to.
                          [default: 0.0.0.0]
  -p, --port INTEGER      Port to bind the DummyDAC server to.  [default:
                          5732]
  --virtual / --physical  Use virtual MACs (00-00-00-00-00-XX) or random
                          physical MACs.  [default: virtual]
  --help                  Show this message and exit.
```

### Network Buffer Configuration

LUCIDAC/REDAC devices stream measurement data via UDP at a fixed send rate. If the
host PC cannot accept and process all incoming samples quickly enough, the device's
internal buffer will overflow, resulting in data loss and errors during acquisition.

To prevent this, we recommend increasing the system's UDP send/receive buffer sizes.
On Linux, add the following to `/etc/sysctl.conf`:

```
net.core.wmem_max=26214400
net.core.rmem_max=26214400
net.core.wmem_default=26214400
net.core.rmem_default=26214400
```

Apply the changes with:

```bash
sudo sysctl -p
```

## Repository structure

This repository is a **uv workspace monorepo** containing two packages that share
the `pybrid` namespace via [PEP 420](https://peps.python.org/pep-0420/) implicit
namespace packages:

```
pybrid-computing/                       (repo root — workspace)
├── pyproject.toml                      (uv workspace root, not a publishable package)
├── packages/
│   ├── pybrid-computing/               (pure-Python library)
│   │   ├── pyproject.toml              (hatchling + uv-dynamic-versioning)
│   │   └── src/
│   │       └── pybrid/                 (NO __init__.py — namespace root)
│   │           ├── base/               (protocol, models, serialisation)
│   │           ├── cli/                (click-based CLI)
│   │           ├── lucidac/            (LUCIDAC device layer)
│   │           ├── lucipy/             (high-level Circuit API + LUCIStack)
│   │           ├── mock/               (DummyDAC mock server)
│   │           ├── redac/              (REDAC device layer)
│   │           └── sim/                (simulator device layer)
│   └── pybrid-computing-native/        (C++ extension via pybind11)
│       ├── pyproject.toml              (scikit-build-core)
│       ├── native/                     (C++ sources: transport, channels, protobuf)
│       │   ├── CMakeLists.txt
│       │   └── bindings.cpp
│       ├── tests/                      (C++ GoogleTest tests)
│       └── src/
│           └── pybrid/                 (NO __init__.py — namespace root)
│               └── native/             (Python wrapper importing _impl)
├── extern/
│   └── pybind11/                       (vendored, not committed — see below)
├── tests/                              (pytest test suite, at repo root)
├── proto/                              (protobuf definitions)
├── docs/                               (Sphinx documentation)
└── examples/                           (usage examples)
```

### Package overview

| Package | Import path | Description |
|---------|-------------|-------------|
| **pybrid-computing** | `pybrid.base`, `pybrid.cli`, `pybrid.lucidac`, `pybrid.lucipy`, `pybrid.mock`, `pybrid.redac`, `pybrid.sim` | Pure-Python library: protocol, models, device layers, CLI, mock server |
| **pybrid-computing-native** | `pybrid.native` | C++ extension providing high-performance UDP/TCP transports and data channels via pybind11 |

Both packages contribute subpackages under the shared `pybrid` namespace. Neither
package has an `__init__.py` at `src/pybrid/` — this is intentional (PEP 420
implicit namespace packages) and required for the namespace to work correctly.

The native extension is an optional accelerator. When it cannot be built or is not
installed, the Python library continues to work — `pybrid.native.NATIVE_AVAILABLE`
will be `False` in that case.

## Getting started as developer

This project is managed via [uv](https://docs.astral.sh/uv/), a fast Python package
manager and project tool.

### Prerequisites

Building the native extension requires a C++17 compiler and CMake:

```bash
# Debian/Ubuntu
sudo apt-get install build-essential cmake

# Fedora
sudo dnf install gcc-c++ cmake

# macOS (Xcode command-line tools include both)
xcode-select --install
```

### Setup with uv

```bash
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone the repository and enter the directory
git clone <repository-url>
cd pybrid-computing

# Vendor pybind11 (not committed — needed for native build)
mkdir -p extern
curl -sL https://github.com/pybind/pybind11/archive/refs/tags/v2.13.6.tar.gz \
  | tar xz -C extern && mv extern/pybind11-2.13.6 extern/pybind11

# Create virtual environment and install all workspace packages + dev tools
uv sync --group dev

# Activate the virtual environment
source .venv/bin/activate
```

### Editable installation

`uv sync` installs both workspace packages in editable mode by default. Source
code changes are applied once you restart pybrid or re-run your script.

### Running the tests

The test suite uses [pytest](https://docs.pytest.org/) with async support via
`pytest-asyncio`. Tests are organized into several categories:

```
tests/
├── unit/          # Unit tests (no external dependencies)
├── integration/   # Integration tests (use mock devices)
├── mock/          # Tests for the mock/DummyDAC infrastructure
├── device/        # Tests requiring real hardware
├── e2e/           # End-to-end CLI tests
└── benchmark/     # Performance tests (excluded by default)
```

#### Basic test execution

```bash
# Run all tests (except benchmarks)
uv run pytest

# Run only unit tests
uv run pytest tests/unit/

# Run with verbose output
uv run pytest -v
```

#### Mock device (DummyDAC)

Most integration and E2E tests use the **DummyDAC**, a mock implementation of
the REDAC protocol that simulates device behavior without requiring real hardware.
The DummyDAC is automatically started by test fixtures when needed.

```bash
# Run integration tests (uses DummyDAC automatically)
uv run pytest tests/integration/

# Run E2E CLI tests (uses DummyDAC automatically)
uv run pytest tests/e2e/
```

Manually starting the `DUmmyDAC` for, e.g. developing against the protobuf-based
protocol is possible through the CLI:
```bash
pybrid dummy --host <HOST IP, defaults to 0.0.0.0> --port <BIND PORT, defaults to 5732>
```

The DummyDAC will behave similar to a LUCIDAC, but ignore the input circuit you sent it.
Instead, it always samples from a shifted sine wave function.

#### Testing with real devices

Device tests require actual hardware and are controlled via environment variables.
Three device types are supported:

| Environment Variable | Device Type | Description |
|---------------------|-------------|-------------|
| `TEST_LUCIDAC_ENDPOINT` | LUCIDAC | Physical LUCIDAC analog computer |
| `TEST_REDAC_ENDPOINT` | REDAC | Physical REDAC analog computer |
| `TEST_SIMULATOR_ENDPOINT` | Simulator | Software simulator (e.g., lucipy) |

The endpoint format is `tcp://host:port` (port defaults to 5732 if not specified):

```bash
# Run device tests against a LUCIDAC
TEST_LUCIDAC_ENDPOINT=tcp://192.168.1.100:5732 uv run pytest tests/device/

# Run device tests against the simulator
TEST_SIMULATOR_ENDPOINT=tcp://localhost:5732 uv run pytest tests/device/

# Run with multiple devices configured
TEST_LUCIDAC_ENDPOINT=tcp://192.168.1.100:5732 \
TEST_SIMULATOR_ENDPOINT=tcp://localhost:5732 \
uv run pytest tests/device/ -v
```

Device tests are **parameterized** by device type, meaning each test appears
separately in the output for each configured device (lucidac, redac, simulator).
Tests will be **skipped** for device types that don't have their endpoint
environment variable set. This makes it easy to see which devices passed or
were skipped in the test output:

```
tests/device/test_accuracy.py::TestHarmonicOscillatorOnDevice::test_harmonic_amplitude[lucidac] PASSED
tests/device/test_accuracy.py::TestHarmonicOscillatorOnDevice::test_harmonic_amplitude[redac] SKIPPED
tests/device/test_accuracy.py::TestHarmonicOscillatorOnDevice::test_harmonic_amplitude[simulator] PASSED
```

Device tests are marked with `@pytest.mark.device` for filtering purposes.

#### Test markers

The test suite uses pytest markers to categorize tests:

- `device` - Tests requiring real hardware (skipped without `TEST_*_ENDPOINT`)
- `benchmark` - Performance tests (excluded from default run)
- `slow` - Tests that take longer to run
- `lucidac` - Tests specific to LUCIDAC
- `redac` - Tests specific to REDAC
- `sim` - Tests specific to simulator

```bash
# Run only device tests
uv run pytest -m device

# Exclude slow tests
uv run pytest -m "not slow"

# Run benchmarks explicitly
uv run pytest tests/benchmark/
```

## Documentation

> **You can read the documentation online at https://anabrid.dev/docs/pybrid/html/**

It is generated by the [Sphinx](https://www.sphinx-doc.org/) documentation which
is part of this repository/package.

## Install

```bash
uv pip install pybrid-computing --index-url https://https://lab.analogparadigm.com/api/v4/projects/pybrid-computing/pybrid-computing/packages/pypi/simple --extra-index-url https://pypi.org/simple`
```

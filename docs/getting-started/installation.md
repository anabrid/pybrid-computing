# Installation

## From PyPI

```bash
pip install pybrid-computing
```

## From source

```bash
git clone https://lab.2b.anabrid.com/2b/pybrid-computing.git
cd pybrid-computing
uv sync --group dev
```

## Optional: native extensions

For accelerated UDP/TCP transports, also install the native package:

```bash
pip install pybrid-computing-native
```

Or from source (requires a C++ compiler and CMake):

```bash
uv sync --group dev  # builds both packages in the workspace
```

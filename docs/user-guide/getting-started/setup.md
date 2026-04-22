# Setup

We assume a working Python installation as described in
[Requirements](./requirements.md). `pybrid` can be installed either
from pre-built binaries served on PyPI, which is the right path for
most users, or from source for developers and on platforms without
published wheels.

In both cases, we recommend installing `pybrid` into a dedicated
[virtual environment](https://docs.python.org/3/library/venv.html) to
avoid dependency conflicts with the rest of your Python setup. While
you can manage virtual environments manually, we find the
[uv package manager](https://docs.astral.sh/uv/) to be the most
convenient option, and for the remainder of this documentation we
assume that `uv` is used for environment and package management.

## Installing from pre-built binaries

Both packages that make up `pybrid` (see [Requirements](./requirements.md))
are available as pre-built wheels on PyPI for the supported operating
systems and architectures. Setting up a fresh environment and
installing `pybrid` with `uv` takes two commands:

```bash
# create a new virtual environment in the .venv/ folder
# using Python 3.13 (the recommended version)
uv venv --python 3.13

# install pybrid-computing (pulls in pybrid-computing-native automatically)
uv pip install pybrid-computing
```

To update an existing installation to the latest release (something
you should do from time to time), pass the `-U` flag:

```bash
uv pip install -U pybrid-computing
```

!!! warning "Keep both package versions in sync"

    The version numbers of `pybrid-computing` and `pybrid-computing-native`
    must always be identical. Installing or updating `pybrid-computing`
    via `uv pip install` keeps the two aligned automatically, but if
    you later pin or upgrade one of them by hand, double-check that the
    versions still match.

## Installing from source

Installing from source is the right path for users on a platform
without pre-built wheels, or for anyone who wants to hack on `pybrid`
itself. It additionally requires a working C++ compiler supporting at
least the C++14 standard and [cmake](https://cmake.org/) (see
[Requirements](./requirements.md) for the full list), and the initial
build typically takes several minutes because the native extension is
compiled locally.

After checking out the source, run the following two commands from
the repository root:

```bash
uv venv --python 3.13

# build both packages and install them into the venv
uv sync
```

To produce distributable binary wheels (for example to share them
with other machines of the same platform), invoke `uv build` once per
package:

```bash
uv build packages/pybrid-computing-native
uv build packages/pybrid-computing
```

This places the platform-specific `.whl` files under the respective
`dist/` directories. Updating a source installation is a matter of
pulling the latest state from git and re-running `uv sync` to rebuild
both packages.

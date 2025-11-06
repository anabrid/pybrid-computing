# Binary Distribution Build Scripts

This directory contains all the necessary scripts and configuration files to build binary-only wheels for `pybrid-computing` using Cython compilation.

## Overview

The binary distribution approach compiles Python source code (`.py`) to native extensions (`.so` on Linux, `.pyd` on Windows) using Cython. This provides:

- **Source code protection**: No Python source code in distributed packages
- **Performance**: Potential performance improvements from Cython compilation
- **Simplified deployment**: Users install via pip without needing Python source

## Architecture

The build system uses a **self-contained containerized approach**:

- **One script**: `docker-build.sh` does everything
- **Two modes**:
  - On host: Builds Docker image and runs itself inside container
  - In container: Performs the actual Cython compilation and wheel building
- **Clean builds**: All tools run in containers, no host pollution

## Directory Structure

```
build-scripts/
├── prepare-cython.py          # Common: Transforms .py → .pyx
├── setup.py.template          # Common: Cython compilation template
├── requirements-build.txt     # Common: Build dependencies
├── README.md                  # Common: This file
└── linux-x86_64/              # Platform-specific: Linux x86_64
    ├── docker-build.sh        # Self-contained build script (run this!)
    ├── Dockerfile             # Container definition
    └── cibuildwheel.toml      # Wheel build configuration
```

### Files Explained

**Common Files** (platform-independent):
- `prepare-cython.py`: Transforms Python source to Cython-compatible format
- `setup.py.template`: Jinja2 template for generating setup.py with Cython config
- `requirements-build.txt`: Build dependencies (Cython, cibuildwheel, etc.)

**Linux x86_64 Files**:
- `docker-build.sh`: **Main script** - self-contained, runs in two modes (host/container)
- `Dockerfile`: Container image with build tools (gcc, Docker CLI, Python)
- `cibuildwheel.toml`: Configuration for building manylinux wheels

## Usage

### Quick Start

**Requirement**: Docker only

Build binary wheels for **all Python versions** (3.11, 3.12, 3.13, 3.14):

```bash
cd /path/to/pybrid-computing
./build-scripts/linux-x86_64/docker-build.sh
```

Build for **specific Python version(s)** (comma-separated, no quotes):

```bash
# Single version
./build-scripts/linux-x86_64/docker-build.sh --python-version 3.11

# Multiple versions
./build-scripts/linux-x86_64/docker-build.sh --python-version 3.11,3.12

# All versions explicitly
./build-scripts/linux-x86_64/docker-build.sh --python-version 3.11,3.12,3.13,3.14
```

**Rebuild from scratch** (clears Docker cache):

```bash
./build-scripts/linux-x86_64/docker-build.sh --no-cache --python-version 3.11
```

### Output

Wheels are created in `dist/` directory:

```
dist/
├── pybrid_computing-0.11.0-cp311-cp311-manylinux2014_x86_64.*.whl  (~21 MB)
├── pybrid_computing-0.11.0-cp312-cp312-manylinux2014_x86_64.*.whl  (~21 MB)
├── pybrid_computing-0.11.0-cp313-cp313-manylinux2014_x86_64.*.whl  (~21 MB)
└── pybrid_computing-0.11.0-cp314-cp314-manylinux2014_x86_64.*.whl  (~21 MB)
```

Each wheel contains:
- 73 compiled native extensions (`.so` files)
- No Python source code (except `__init__.py` and protobuf files)
- Compatible with manylinux2014+ (broad Linux compatibility)

All build dependencies and tools are installed inside the container, keeping your host system clean.

## Build Process Details

### High-Level Flow

When you run `docker-build.sh`, it:

1. **On Host**: Builds Docker image with all build tools
2. **On Host**: Runs itself inside the container (`IN_CONTAINER=true`)
3. **In Container**: Performs the actual build (steps below)
4. **In Container**: Copies wheels to mounted `/dist` volume
5. **On Host**: Wheels appear in your `dist/` directory

### Step 1: Source Preparation (in container)

The `prepare-cython.py` script transforms the source:

1. Copies `pybrid/` to `build-temp/pybrid/`
2. Renames `.py` → `.pyx` (except `__init__.py` and `*_pb2.py`)
3. Generates `build-temp/pyproject.toml` with Cython as build dependency
4. Generates `build-temp/setup.py` from template
5. Extracts metadata from `pyproject.toml`

**Files excluded from Cython compilation:**
- All `__init__.py` files (kept as pure Python)
- Protobuf-generated files (`*_pb2.py`)

### Step 2: Wheel Building (in container)

Using `cibuildwheel`:

1. Creates isolated manylinux build environments (per Python version)
2. Installs build dependencies (Cython, setuptools, etc.)
3. Runs Cython compiler to transform `.pyx` → `.c`
4. Compiles C code to native extensions (`.so` files)
5. Packages into manylinux wheels
6. Repairs wheels with `auditwheel` for broad compatibility

### Step 3: Copy to Host

Wheels are copied from container's `/build/dist/` to the mounted `/dist/` volume, which appears as `dist/` on your host.

## Important Notes

### Async/Await Support

The project heavily uses async/await (142+ async functions). The build configuration ensures:

- Cython >= 3.1.6 (full async/await support)
- `language_level = "3"` in compiler directives
- Avoids Cython 3.1.0 (known memory leak issues)

### Protobuf Files

Protobuf-generated files (`*_pb2.py`) are **NOT** compiled to Cython. They remain as pure Python for compatibility with the protobuf runtime.

### Performance Considerations

The build uses these compiler directives for performance:

- `boundscheck = False`: Disable bounds checking
- `wraparound = False`: Disable negative indexing
- `cdivision = True`: Use C division semantics
- `nonecheck = False`: Disable None checks

These are safe because the code has been well-tested with the pure Python interpreter.

## Build Artifacts

After a successful build:

```
dist/
  └── pybrid_computing-0.11.0-cp311-cp311-manylinux_2_17_x86_64.whl
  └── pybrid_computing-0.11.0-cp312-cp312-manylinux_2_17_x86_64.whl
  └── ...

build-temp/          # Temporary build directory (gitignored)
  ├── pybrid/        # Transformed package (.pyx files)
  ├── setup.py       # Generated setup script
  ├── README.md      # Copied from project root
  └── LICENSE        # Copied from project root
```

## Troubleshooting

### Docker Not Found

Ensure Docker is installed and running:
```bash
docker --version
docker ps
```

If `docker ps` fails, start Docker:
```bash
sudo systemctl start docker
# Or on macOS: start Docker Desktop
```

### Build Fails with Image Tag Error

If you see errors like `invalid tag` or `invalid reference format`, ensure:
- Python version doesn't contain invalid characters
- Use comma-separated versions without quotes: `3.11,3.12` (not `"3.11 3.12"`)

### Wheels Not Appearing in dist/

Check that:
1. The build completed successfully (no errors at the end)
2. Docker volume mount is working: `ls -lh dist/`
3. Permissions are correct (wheels may be owned by root)

To fix permissions:
```bash
sudo chown -R $USER:$USER dist/
```

### Build is Slow

First build takes longer due to:
- Docker image creation
- Downloading dependencies
- Compiling 73 modules

Subsequent builds are faster due to Docker layer caching. Use `--no-cache` only when needed.

## Future Enhancements

When ready for full multi-platform support, create additional platform directories:

```
build-scripts/
├── linux-x86_64/           # ✅ Done
├── linux-arm64/            # Future: Linux ARM64
├── macos-x86_64/           # Future: macOS Intel
├── macos-arm64/            # Future: macOS Apple Silicon
└── windows-amd64/          # Future: Windows 64-bit
```

Each platform directory would contain:
- `docker-build.sh` (or `.ps1` for Windows) - Self-contained build script
- `Dockerfile` - Platform-specific container
- `cibuildwheel.toml` - Platform-specific wheel configuration

Additional tasks:
- Set up CI/CD pipeline with platform-specific runners
- Add code signing for macOS and Windows wheels
- Test wheels on actual target platforms

## References

- [Cython Documentation](https://cython.readthedocs.io/)
- [cibuildwheel Documentation](https://cibuildwheel.readthedocs.io/)
- [PEP 427 - Wheel Binary Package Format](https://www.python.org/dev/peps/pep-0427/)

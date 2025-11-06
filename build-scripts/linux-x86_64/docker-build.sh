#!/bin/bash
#
# Binary wheel builder for pybrid-computing
#
# This script can run in two modes:
# 1. On host: Builds Docker image and runs itself inside container
# 2. Inside container: Performs the actual build
#
# Usage:
#   ./docker-build.sh [--no-cache] [--python-version X.Y,X.Y,...]
#
# Options:
#   --no-cache          Build Docker image from scratch
#   --python-version    Python version(s) to build wheels for (comma-separated)
#                       Examples:
#                         --python-version 3.11           # Build only for Python 3.11
#                         --python-version 3.11,3.12      # Build for 3.11 and 3.12
#                         --python-version 3.11,3.12,3.13 # Build for 3.11, 3.12, and 3.13
#                       Default: Build for ALL versions (3.11, 3.12, 3.13, 3.14)
#

set -euo pipefail

# Detect if we're running inside a container
IN_CONTAINER=${IN_CONTAINER:-false}

#==============================================================================
# BUILD INSIDE CONTAINER MODE
#==============================================================================

if [ "${IN_CONTAINER}" = "true" ]; then
    # Colors for output
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    BLUE='\033[0;34m'
    NC='\033[0m'

    log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
    log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
    log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

    echo ""
    echo "========================================================================"
    echo "  Binary Wheel Build for pybrid-computing"
    echo "========================================================================"
    echo ""

    cd /build

    # Step 1: Prepare source for Cython compilation
    log_info "Step 1: Preparing source for Cython compilation..."
    python3 build-scripts/prepare-cython.py
    log_success "Source preparation complete"

    # Step 2: Build wheels with cibuildwheel
    log_info "Step 2: Building wheels with cibuildwheel..."
    cd build-temp

    # Set cibuildwheel config
    export CIBUILDWHEEL_CONFIG=/build/build-scripts/linux-x86_64/cibuildwheel.toml

    # CIBW_BUILD can be set via docker run -e to control which versions to build
    log_info "CIBW_BUILD=${CIBW_BUILD:-<from config>}"

    python3 -m cibuildwheel --platform linux --output-dir /build/dist

    log_success "Wheel building complete"

    # Step 3: Copy wheels to mounted volume
    log_info "Step 3: Copying wheels to /dist/..."
    if ls /build/dist/*.whl 1> /dev/null 2>&1; then
        cp -v /build/dist/*.whl /dist/
        log_success "Copied $(ls /build/dist/*.whl | wc -l) wheel(s) to /dist/"

        echo ""
        echo "Built wheels:"
        ls -lh /dist/*.whl
    else
        log_error "No wheels found in /build/dist/"
        exit 1
    fi

    echo ""
    echo "========================================================================"
    echo "  Build Complete!"
    echo "========================================================================"
    echo ""

    exit 0
fi

#==============================================================================
# HOST MODE (BUILD AND RUN CONTAINER)
#==============================================================================

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_SCRIPTS_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${BUILD_SCRIPTS_DIR}/.." && pwd)"

# Default values
NO_CACHE=""
PYTHON_VERSION=""  # Empty means build all versions

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --no-cache)
            NO_CACHE="--no-cache"
            shift
            ;;
        --python-version)
            PYTHON_VERSION="$2"
            shift 2
            ;;
        *)
            shift
            ;;
    esac
done

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if Docker is available
if ! command -v docker &> /dev/null; then
    log_error "Docker not found. Please install Docker first."
    exit 1
fi

echo ""
echo "========================================================================"
echo "  Docker Binary Wheel Build for pybrid-computing"
echo "========================================================================"
echo ""

log_info "Project root: ${PROJECT_ROOT}"

# Convert Python version(s) to cibuildwheel format
# Empty PYTHON_VERSION means build all versions (use config file)
CIBW_BUILD_SPEC=""
if [ -n "${PYTHON_VERSION}" ]; then
    # Convert each version to cibuildwheel format (e.g., "3.11,3.12" -> "cp311-manylinux_x86_64 cp312-manylinux_x86_64")
    CIBW_BUILD_PARTS=()
    IFS=',' read -ra VERSION_ARRAY <<< "${PYTHON_VERSION}"
    for ver in "${VERSION_ARRAY[@]}"; do
        ver_compact=$(echo ${ver} | sed 's/\.//')
        CIBW_BUILD_PARTS+=("cp${ver_compact}-manylinux_x86_64")
    done
    CIBW_BUILD_SPEC=$(IFS=' '; echo "${CIBW_BUILD_PARTS[*]}")
    log_info "Building wheels for: ${CIBW_BUILD_SPEC}"
else
    log_info "Building wheels for: ALL versions (from config)"
fi

# Create dist directory if it doesn't exist
mkdir -p "${PROJECT_ROOT}/dist"

# Determine container Python version (use first specified version, or 3.11 default)
CONTAINER_PYTHON_VERSION="${PYTHON_VERSION%%,*}"  # Get first version from comma-separated list
if [ -z "${CONTAINER_PYTHON_VERSION}" ]; then
    CONTAINER_PYTHON_VERSION="3.11"
fi
log_info "Container Python version: ${CONTAINER_PYTHON_VERSION}"

# Update Dockerfile with container Python version
DOCKERFILE="${SCRIPT_DIR}/Dockerfile"
TEMP_DOCKERFILE="${SCRIPT_DIR}/Dockerfile.tmp"
sed "s/FROM python:3.11-slim/FROM python:${CONTAINER_PYTHON_VERSION}-slim/" "${DOCKERFILE}" > "${TEMP_DOCKERFILE}"

# Build Docker image
log_info "Building Docker image..."
docker build \
    ${NO_CACHE} \
    -t pybrid-build-linux-x86_64:${CONTAINER_PYTHON_VERSION} \
    -f "${TEMP_DOCKERFILE}" \
    "${PROJECT_ROOT}"

rm "${TEMP_DOCKERFILE}"
log_success "Docker image built"

# Run build in container
log_info "Building wheels in container..."
log_info "Mounting Docker socket for cibuildwheel..."

# Run build in container using docker run
docker run --rm \
    -v "${PROJECT_ROOT}/dist:/dist" \
    -v /var/run/docker.sock:/var/run/docker.sock \
    -e IN_CONTAINER=true \
    ${CIBW_BUILD_SPEC:+-e "CIBW_BUILD=${CIBW_BUILD_SPEC}"} \
    pybrid-build-linux-x86_64:${CONTAINER_PYTHON_VERSION} \
    /build/build-scripts/linux-x86_64/docker-build.sh

log_success "Wheels built successfully"

# List built wheels
log_info "Built wheels:"
for wheel in "${PROJECT_ROOT}/dist"/*.whl; do
    if [ -f "$wheel" ]; then
        echo "  - $(basename "$wheel")"
    fi
done

echo ""
echo "========================================================================"
echo "  Build Complete!"
echo "========================================================================"
echo ""
log_success "Wheels are available in: ${PROJECT_ROOT}/dist"
echo ""

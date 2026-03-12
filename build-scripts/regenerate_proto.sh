#!/usr/bin/env bash
#
# Builds protobuf v26.1 from source and regenerates the pre-committed
# C++ (main.pb.h / main.pb.cc) and Python (main_pb2.py / main_pb2.pyi)
# files.  Run this whenever proto/main.proto changes.
#
# Usage:
#   ./build-scripts/regenerate_proto.sh
#
# The script is self-contained: it clones protobuf, builds only protoc,
# runs code generation, and cleans up.  Requires cmake, make/ninja, and
# a C++ toolchain.

set -euo pipefail

PROTOBUF_TAG="v32.0"
PROTO_SRC="proto/main.proto"
CPP_OUTPUT_DIR="packages/pybrid-computing-native/native/pybrid/proto"
PY_OUTPUT_DIR="packages/pybrid-computing/src/pybrid/base/proto"

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PROTO_SRC="${REPO_ROOT}/${PROTO_SRC}"
CPP_OUTPUT_DIR="${REPO_ROOT}/${CPP_OUTPUT_DIR}"
PY_OUTPUT_DIR="${REPO_ROOT}/${PY_OUTPUT_DIR}"

if [[ ! -f "${PROTO_SRC}" ]]; then
    echo "Error: ${PROTO_SRC} not found. Run from the repository root." >&2
    exit 1
fi

BUILD_DIR="$(mktemp -d)"
trap 'rm -rf "${BUILD_DIR}"' EXIT

echo "==> Cloning protobuf ${PROTOBUF_TAG} into ${BUILD_DIR}..."
git clone --depth 1 --branch "${PROTOBUF_TAG}" \
    --recurse-submodules --shallow-submodules \
    https://github.com/protocolbuffers/protobuf.git \
    "${BUILD_DIR}/protobuf"

echo "==> Building protoc..."
cmake -S "${BUILD_DIR}/protobuf" -B "${BUILD_DIR}/build" \
    -DCMAKE_BUILD_TYPE=Release \
    -Dprotobuf_BUILD_TESTS=OFF \
    -Dprotobuf_BUILD_CONFORMANCE=OFF \
    -Dprotobuf_BUILD_EXAMPLES=OFF \
    -Dprotobuf_INSTALL=OFF \
    -Dprotobuf_ABSL_PROVIDER=module \
    -DABSL_BUILD_TESTING=OFF \
    -DABSL_ENABLE_INSTALL=OFF

cmake --build "${BUILD_DIR}/build" --target protoc -j "$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 4)"

PROTOC="${BUILD_DIR}/build/protoc"
if [[ ! -x "${PROTOC}" ]]; then
    echo "Error: protoc binary not found at ${PROTOC}" >&2
    echo "Searching for it in build directory..." >&2
    PROTOC="$(find "${BUILD_DIR}/build" -name protoc -type f | head -1)"
    if [[ -z "${PROTOC}" || ! -x "${PROTOC}" ]]; then
        echo "Error: could not locate protoc binary" >&2
        exit 1
    fi
fi

echo "==> protoc version: $(${PROTOC} --version)"

echo "==> Generating C++ sources..."
"${PROTOC}" \
    --proto_path="$(dirname "${PROTO_SRC}")" \
    --cpp_out="${CPP_OUTPUT_DIR}" \
    "$(basename "${PROTO_SRC}")"

echo "==> Generating Python sources..."
"${PROTOC}" \
    --proto_path="$(dirname "${PROTO_SRC}")" \
    --python_out="${PY_OUTPUT_DIR}" \
    --pyi_out="${PY_OUTPUT_DIR}" \
    "$(basename "${PROTO_SRC}")"

echo "==> Generated files:"
ls -la "${CPP_OUTPUT_DIR}/main.pb.h" "${CPP_OUTPUT_DIR}/main.pb.cc"
ls -la "${PY_OUTPUT_DIR}/main_pb2.py" "${PY_OUTPUT_DIR}/main_pb2.pyi"

echo "==> Done. Verify the generated files and commit them."

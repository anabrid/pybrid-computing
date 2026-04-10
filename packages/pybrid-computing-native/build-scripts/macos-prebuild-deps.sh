#!/usr/bin/env bash
## Pre-build abseil + protobuf for macOS CI wheels.
## Produces universal (x86_64 + arm64) static libraries.
## Installs to /tmp/pybrid_deps; skips rebuild if versions match.

set -euo pipefail

INSTALL_PREFIX="/tmp/pybrid_deps"
BUILD_DIR="/tmp/pybrid_deps_build"
ABSEIL_TAG="lts_2025_01_27"
PROTOBUF_TAG="v32.0"

VERSION_FILE="$INSTALL_PREFIX/.deps_version"
EXPECTED_VERSION="${ABSEIL_TAG}_${PROTOBUF_TAG}"

if [[ -f "$VERSION_FILE" ]]; then
    current=$(tr -d '[:space:]' < "$VERSION_FILE")
    if [[ "$current" == "$EXPECTED_VERSION" ]]; then
        echo "Pre-built deps up-to-date ($EXPECTED_VERSION), skipping."
        exit 0
    fi
fi

echo "Building dependencies ($EXPECTED_VERSION) ..."

# On newer macOS (26+), clang may not find C++ stdlib headers via its default
# search paths. Detect the headers location and inject -isystem if needed.
CXX_FLAGS=""
SDKROOT="${SDKROOT:-$(xcrun --show-sdk-path 2>/dev/null || true)}"
if [[ -n "$SDKROOT" && -d "$SDKROOT/usr/include/c++/v1" ]]; then
    CXX_FLAGS="-isystem $SDKROOT/usr/include/c++/v1"
else
    CLANG_PATH=$(xcrun --find clang++ 2>/dev/null || true)
    if [[ -n "$CLANG_PATH" ]]; then
        TOOLCHAIN_DIR=$(dirname "$(dirname "$CLANG_PATH")")
        if [[ -d "$TOOLCHAIN_DIR/include/c++/v1" ]]; then
            CXX_FLAGS="-isystem $TOOLCHAIN_DIR/include/c++/v1"
        fi
    fi
fi
if [[ -n "$CXX_FLAGS" ]]; then
    echo "Using extra CXX flags: $CXX_FLAGS"
fi

rm -rf "$BUILD_DIR" "$INSTALL_PREFIX"

# -- Abseil ----------------------------------------------------------------

git clone --depth 1 --branch "$ABSEIL_TAG" \
    https://github.com/abseil/abseil-cpp.git "$BUILD_DIR/abseil-src"

cmake -G Ninja -S "$BUILD_DIR/abseil-src" -B "$BUILD_DIR/abseil-build" \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX="$INSTALL_PREFIX" \
    -DCMAKE_CXX_STANDARD=17 \
    -DCMAKE_CXX_FLAGS="$CXX_FLAGS" \
    -DCMAKE_POSITION_INDEPENDENT_CODE=ON \
    -DCMAKE_OSX_ARCHITECTURES="x86_64;arm64" \
    -DBUILD_SHARED_LIBS=OFF \
    -DABSL_PROPAGATE_CXX_STD=ON \
    -DABSL_BUILD_TESTING=OFF

cmake --build "$BUILD_DIR/abseil-build" --parallel 1
cmake --install "$BUILD_DIR/abseil-build"

# -- Protobuf (links pre-built abseil) ------------------------------------

git clone --depth 1 --branch "$PROTOBUF_TAG" \
    https://github.com/protocolbuffers/protobuf.git "$BUILD_DIR/protobuf-src"
git -C "$BUILD_DIR/protobuf-src" submodule update --init --depth 1 third_party/utf8_range

cmake -G Ninja -S "$BUILD_DIR/protobuf-src" -B "$BUILD_DIR/protobuf-build" \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX="$INSTALL_PREFIX" \
    -DCMAKE_PREFIX_PATH="$INSTALL_PREFIX" \
    -DCMAKE_CXX_STANDARD=17 \
    -DCMAKE_CXX_FLAGS="$CXX_FLAGS" \
    -DCMAKE_POSITION_INDEPENDENT_CODE=ON \
    -DCMAKE_OSX_ARCHITECTURES="x86_64;arm64" \
    -DBUILD_SHARED_LIBS=OFF \
    -Dprotobuf_BUILD_TESTS=OFF \
    -Dprotobuf_BUILD_PROTOC_BINARIES=OFF \
    -Dprotobuf_BUILD_LIBUPB=OFF \
    -Dprotobuf_INSTALL=ON

cmake --build "$BUILD_DIR/protobuf-build" --parallel 1
cmake --install "$BUILD_DIR/protobuf-build"

# -- Cleanup ---------------------------------------------------------------

echo "$EXPECTED_VERSION" > "$VERSION_FILE"
rm -rf "$BUILD_DIR"

echo "Dependencies installed to $INSTALL_PREFIX"

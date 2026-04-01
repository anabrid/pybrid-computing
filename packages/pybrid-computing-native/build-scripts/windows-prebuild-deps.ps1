## Pre-build abseil + protobuf for Windows CI wheels.
## Installs to C:\pybrid_deps; skips rebuild if versions match.

$ErrorActionPreference = "Stop"

# cmake/ninja are not on PATH in cibuildwheel's before-all context.
# Install as uv tools and add their bin directory to this session's PATH.
uv tool install cmake --quiet
uv tool install ninja --quiet
$env:Path = "$(uv tool dir --bin);$env:Path"

# Ninja needs the MSVC toolchain on PATH. Find and activate vcvars64.
$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
if (Test-Path $vswhere) {
    $vsPath = & $vswhere -latest -property installationPath
    $vcvars = "$vsPath\VC\Auxiliary\Build\vcvars64.bat"
    if (Test-Path $vcvars) {
        # Import vcvars environment into this PowerShell session
        cmd /c "`"$vcvars`" >nul 2>&1 && set" | ForEach-Object {
            if ($_ -match '^([^=]+)=(.*)$') {
                [System.Environment]::SetEnvironmentVariable($Matches[1], $Matches[2], 'Process')
            }
        }
        Write-Host "MSVC environment loaded from $vcvars"
    }
}
$INSTALL_PREFIX = "C:\pybrid_deps"
$BUILD_DIR      = "C:\pybrid_deps_build"
$ABSEIL_TAG     = "lts_2025_01_27"
$PROTOBUF_TAG   = "v32.0"

$VERSION_FILE     = "$INSTALL_PREFIX\.deps_version"
$EXPECTED_VERSION = "${ABSEIL_TAG}_${PROTOBUF_TAG}"

if (Test-Path $VERSION_FILE) {
    $current = (Get-Content $VERSION_FILE -Raw).Trim()
    if ($current -eq $EXPECTED_VERSION) {
        Write-Host "Pre-built deps up-to-date ($EXPECTED_VERSION), skipping."
        exit 0
    }
}

Write-Host "Building dependencies ($EXPECTED_VERSION) ..."

if (Test-Path $BUILD_DIR)      { Remove-Item -Recurse -Force $BUILD_DIR }
if (Test-Path $INSTALL_PREFIX) { Remove-Item -Recurse -Force $INSTALL_PREFIX }

# -- Abseil ----------------------------------------------------------------

git clone --depth 1 --branch $ABSEIL_TAG `
    https://github.com/abseil/abseil-cpp.git "$BUILD_DIR\abseil-src"

cmake -G Ninja -S "$BUILD_DIR\abseil-src" -B "$BUILD_DIR\abseil-build" `
    -DCMAKE_BUILD_TYPE=Release `
    -DCMAKE_INSTALL_PREFIX="$INSTALL_PREFIX" `
    -DCMAKE_CXX_STANDARD=17 `
    -DCMAKE_POSITION_INDEPENDENT_CODE=ON `
    -DBUILD_SHARED_LIBS=OFF `
    -DABSL_PROPAGATE_CXX_STD=ON `
    -DABSL_BUILD_TESTING=OFF

cmake --build "$BUILD_DIR\abseil-build" --parallel 4
cmake --install "$BUILD_DIR\abseil-build"

# -- Protobuf (links pre-built abseil) ------------------------------------

git clone --depth 1 --branch $PROTOBUF_TAG `
    https://github.com/protocolbuffers/protobuf.git "$BUILD_DIR\protobuf-src"
git -C "$BUILD_DIR\protobuf-src" submodule update --init --depth 1 third_party/utf8_range

cmake -G Ninja -S "$BUILD_DIR\protobuf-src" -B "$BUILD_DIR\protobuf-build" `
    -DCMAKE_BUILD_TYPE=Release `
    -DCMAKE_INSTALL_PREFIX="$INSTALL_PREFIX" `
    -DCMAKE_PREFIX_PATH="$INSTALL_PREFIX" `
    -DCMAKE_CXX_STANDARD=17 `
    -DCMAKE_POSITION_INDEPENDENT_CODE=ON `
    -DBUILD_SHARED_LIBS=OFF `
    -Dprotobuf_BUILD_TESTS=OFF `
    -Dprotobuf_BUILD_PROTOC_BINARIES=OFF `
    -Dprotobuf_MSVC_STATIC_RUNTIME=OFF `
    -Dprotobuf_BUILD_LIBUPB=OFF `
    -Dprotobuf_INSTALL=ON

cmake --build "$BUILD_DIR\protobuf-build" --parallel 4
cmake --install "$BUILD_DIR\protobuf-build"

# -- Cleanup ---------------------------------------------------------------

Set-Content -Path $VERSION_FILE -Value $EXPECTED_VERSION
Remove-Item -Recurse -Force $BUILD_DIR

Write-Host "Dependencies installed to $INSTALL_PREFIX"

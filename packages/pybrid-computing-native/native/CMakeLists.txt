cmake_minimum_required(VERSION 3.18)

# macOS: auto-detect SDK so C++ stdlib headers are always found,
# even when SDKROOT is not propagated through the build tool chain.
if(APPLE AND NOT CMAKE_OSX_SYSROOT)
    execute_process(
        COMMAND xcrun --show-sdk-path
        OUTPUT_VARIABLE CMAKE_OSX_SYSROOT
        OUTPUT_STRIP_TRAILING_WHITESPACE
    )
endif()

project(pybrid_computing_native CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

# MSVC: compile multiple source files in parallel within a single project.
if(MSVC)
    add_compile_options(/MP)
endif()

# Pre-built dependencies prefix (e.g. from CI prebuild script).
# Applies to both abseil and protobuf find_package() calls below.
if(DEFINED ENV{PYBRID_DEPS_PREFIX})
    list(APPEND CMAKE_PREFIX_PATH "$ENV{PYBRID_DEPS_PREFIX}")
elseif(DEFINED PYBRID_DEPS_PREFIX)
    list(APPEND CMAKE_PREFIX_PATH "${PYBRID_DEPS_PREFIX}")
endif()

# GCC 15+ compatibility: force include <cstdint> for uintptr_t in abseil-cpp
if(CMAKE_CXX_COMPILER_ID STREQUAL "GNU" AND CMAKE_CXX_COMPILER_VERSION VERSION_GREATER_EQUAL "15")
    add_compile_options("$<$<COMPILE_LANGUAGE:CXX>:-include;cstdint>")
endif()

# macOS: on newer macOS (26+), clang may not find C++ stdlib headers via its
# default search paths. Try the SDK and toolchain locations explicitly.
if(APPLE)
    set(_CXX_HEADERS "")
    if(CMAKE_OSX_SYSROOT AND IS_DIRECTORY "${CMAKE_OSX_SYSROOT}/usr/include/c++/v1")
        set(_CXX_HEADERS "${CMAKE_OSX_SYSROOT}/usr/include/c++/v1")
    else()
        execute_process(
            COMMAND xcrun --find clang++
            OUTPUT_VARIABLE _CLANG_PATH
            OUTPUT_STRIP_TRAILING_WHITESPACE
        )
        get_filename_component(_TOOLCHAIN_BIN "${_CLANG_PATH}" DIRECTORY)
        get_filename_component(_TOOLCHAIN "${_TOOLCHAIN_BIN}" DIRECTORY)
        if(IS_DIRECTORY "${_TOOLCHAIN}/include/c++/v1")
            set(_CXX_HEADERS "${_TOOLCHAIN}/include/c++/v1")
        endif()
    endif()
    if(_CXX_HEADERS)
        add_compile_options("$<$<COMPILE_LANGUAGE:CXX>:-isystem;${_CXX_HEADERS}>")
        # Also needed for check_cxx_source_compiles() in dependencies (e.g.
        # protobuf's builtin-atomics test), which don't use add_compile_options.
        set(CMAKE_REQUIRED_FLAGS "${CMAKE_REQUIRED_FLAGS} -isystem ${_CXX_HEADERS}")
    endif()
endif()

# Options
option(PYBRID_USE_SYSTEM_GTEST "Use system GoogleTest instead of FetchContent" OFF)
option(PYBRID_BUILD_TESTS "Build C++ tests (only when PYBRID_BUILD_PYTHON is OFF)" OFF)
option(PYBRID_ENABLE_SANITIZERS "Enable address and thread sanitizers" OFF)
option(PYBRID_BUILD_PYTHON "Build Python extension" OFF)

# For Python wheel builds: vendor protobuf/abseil from source (static linking)
# to avoid runtime dependency on system-installed shared libraries.
# When PYBRID_DEPS_PREFIX is set (e.g. Windows CI pre-built static deps),
# those libraries are used instead.
set(_PYBRID_VENDOR_DEPS FALSE)
if(PYBRID_BUILD_PYTHON)
    if(NOT DEFINED PYBRID_DEPS_PREFIX AND NOT DEFINED ENV{PYBRID_DEPS_PREFIX})
        set(_PYBRID_VENDOR_DEPS TRUE)
        message(STATUS "Python wheel build: vendoring protobuf/abseil from source (static)")
    endif()
endif()

# Include FetchContent for dependency management
include(FetchContent)

# Fetch standalone Asio (header-only)
FetchContent_Declare(
    asio
    GIT_REPOSITORY https://github.com/chriskohlhoff/asio.git
    GIT_TAG asio-1-36-0
    GIT_SHALLOW TRUE
    GIT_PROGRESS TRUE
    EXCLUDE_FROM_ALL
)
FetchContent_MakeAvailable(asio)

# Create interface library for Asio
add_library(asio_standalone INTERFACE)
target_include_directories(asio_standalone INTERFACE
    ${asio_SOURCE_DIR}/asio/include
)
target_compile_definitions(asio_standalone INTERFACE
    ASIO_STANDALONE
    ASIO_NO_DEPRECATED
    $<$<PLATFORM_ID:Windows>:_WIN32_WINNT=0x0601>
)
if(WIN32)
    target_link_libraries(asio_standalone INTERFACE ws2_32 wsock32)
endif()
if(UNIX AND NOT APPLE)
    target_link_libraries(asio_standalone INTERFACE pthread)
endif()

# Fetch concurrentqueue (header-only)
FetchContent_Declare(
    concurrentqueue
    GIT_REPOSITORY https://github.com/cameron314/concurrentqueue.git
    GIT_TAG v1.0.4
    GIT_SHALLOW TRUE
    GIT_PROGRESS TRUE
    EXCLUDE_FROM_ALL
)
FetchContent_MakeAvailable(concurrentqueue)

# Abseil: required by protobuf.  Use a pre-installed build when available
# (e.g. /home/dthuerck/install) so the ABI matches protobuf v32+.
# Set PYBRID_ABSEIL_PREFIX to override the search path.
# Skipped for vendored (Python wheel) builds to avoid linking system shared libs.
if(NOT _PYBRID_VENDOR_DEPS)
    if(DEFINED ENV{PYBRID_ABSEIL_PREFIX})
        list(APPEND CMAKE_PREFIX_PATH "$ENV{PYBRID_ABSEIL_PREFIX}")
    elseif(DEFINED PYBRID_ABSEIL_PREFIX)
        list(APPEND CMAKE_PREFIX_PATH "${PYBRID_ABSEIL_PREFIX}")
    endif()
    find_package(absl QUIET CONFIG)
endif()
if(absl_FOUND)
    message(STATUS "Using system Abseil ${absl_VERSION} from ${absl_DIR}")
else()
    message(STATUS "Abseil not found or vendored — fetching via FetchContent")
    FetchContent_Declare(
        abseil-cpp
        GIT_REPOSITORY https://github.com/abseil/abseil-cpp.git
        GIT_TAG        lts_2025_01_27
        GIT_SHALLOW TRUE
        GIT_PROGRESS TRUE
        EXCLUDE_FROM_ALL
    )
    set(ABSL_PROPAGATE_CXX_STD ON CACHE BOOL "" FORCE)
    set(ABSL_BUILD_TESTING OFF CACHE BOOL "" FORCE)
    set(ABSL_ENABLE_INSTALL OFF CACHE BOOL "" FORCE)
    set(BUILD_SHARED_LIBS OFF CACHE BOOL "" FORCE)
    FetchContent_MakeAvailable(abseil-cpp)
endif()

# Protobuf: use pre-installed build when available, otherwise build from source.
# Pre-generated .pb.cc/.pb.h files require ABI-compatible protobuf v32.
# Skipped for vendored (Python wheel) builds to avoid linking system shared libs.
if(NOT _PYBRID_VENDOR_DEPS)
    find_package(protobuf QUIET CONFIG)
endif()
if(protobuf_FOUND)
    message(STATUS "Using system Protobuf ${protobuf_VERSION} from ${protobuf_DIR}")
else()
    message(STATUS "Protobuf not found or vendored — fetching via FetchContent")
    # GCC >=14 on aarch64 accepts clang::musttail but the ABI rejects tail
    # calls when return types differ, breaking protobuf's TcParser.  Patch
    # port_def.inc to drop aarch64 from the musttail architecture list.
    # See https://github.com/protocolbuffers/protobuf/issues/22367
    if(CMAKE_CXX_COMPILER_ID STREQUAL "GNU"
       AND CMAKE_SYSTEM_PROCESSOR MATCHES "aarch64|arm")
        set(_pb_patch
            PATCH_COMMAND sed -i "s/defined(__aarch64__) || //"
            src/google/protobuf/port_def.inc)
    else()
        set(_pb_patch "")
    endif()
    FetchContent_Declare(
        protobuf
        GIT_REPOSITORY https://github.com/protocolbuffers/protobuf.git
        GIT_TAG        v32.0
        GIT_SHALLOW TRUE
        GIT_PROGRESS TRUE
        GIT_SUBMODULES "third_party/utf8_range"
        EXCLUDE_FROM_ALL
        ${_pb_patch}
    )
    set(protobuf_BUILD_TESTS OFF CACHE BOOL "" FORCE)
    set(protobuf_BUILD_PROTOC_BINARIES OFF CACHE BOOL "" FORCE)
    set(protobuf_MSVC_STATIC_RUNTIME OFF CACHE BOOL "" FORCE)
    set(protobuf_INSTALL OFF CACHE BOOL "" FORCE)
    set(protobuf_BUILD_LIBUPB OFF CACHE BOOL "" FORCE)
    set(BUILD_SHARED_LIBS OFF CACHE BOOL "" FORCE)
    FetchContent_MakeAvailable(protobuf)
endif()

# Library target (header-only for buffer classes)
add_library(pybrid_headers INTERFACE)
target_include_directories(pybrid_headers INTERFACE
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${concurrentqueue_SOURCE_DIR}
)

# Static library for transport classes (used by both tests and Python extension)
add_library(pybrid_native_lib STATIC
    pybrid/transport/udp_socket.cpp
    pybrid/transport/tcp_transport.cpp
    pybrid/transport/tcp_server.cpp
    pybrid/channel/data_channel.cpp
    pybrid/channel/control_channel.cpp
    pybrid/channel/sample_decoding_data_channel.cpp
    pybrid/proxy/proxy_server.cpp
    pybrid/proxy/proxy_message_handlers.cpp
    pybrid/utils/protobuf_helpers.cpp
    pybrid/proto/main.pb.cc
)
target_link_libraries(pybrid_native_lib PUBLIC pybrid_headers asio_standalone protobuf::libprotobuf)
target_include_directories(pybrid_native_lib PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${CMAKE_CURRENT_SOURCE_DIR}/pybrid/proto
)
# Windows: wingdi.h defines `#define ERROR 0` which conflicts with protobuf's
# RunState::ERROR enum value. NOGDI prevents wingdi.h from being included.
target_compile_definitions(pybrid_native_lib PUBLIC $<$<PLATFORM_ID:Windows>:NOGDI>)

# Python extension (optional)
if(PYBRID_BUILD_PYTHON)
    find_package(Python COMPONENTS Interpreter Development.Module REQUIRED)
    find_package(pybind11 CONFIG REQUIRED)

    pybind11_add_module(_impl MODULE bindings.cpp)
    target_link_libraries(_impl PRIVATE pybrid_native_lib)

    # Install into pybrid/native package (scikit-build-core handles the wheel prefix)
    install(TARGETS _impl LIBRARY DESTINATION pybrid/native)
endif()

# Testing (opt-in, only when not building for Python/wheel)
if(PYBRID_BUILD_TESTS AND NOT PYBRID_BUILD_PYTHON)
    enable_testing()

    if(PYBRID_USE_SYSTEM_GTEST)
        find_package(GTest REQUIRED)
    else()
        FetchContent_Declare(
            googletest
            GIT_REPOSITORY https://github.com/google/googletest.git
            GIT_TAG v1.17.0
            GIT_SHALLOW TRUE
        )
        # Prevent GoogleTest from overriding compiler/linker options
        set(gtest_force_shared_crt ON CACHE BOOL "" FORCE)
        # Disable GoogleTest installation
        set(INSTALL_GTEST OFF CACHE BOOL "" FORCE)
        FetchContent_MakeAvailable(googletest)
    endif()

    # Buffer tests (header-only)
    add_executable(pybrid_buffer_tests ${CMAKE_CURRENT_SOURCE_DIR}/../tests/test_buffer.cpp)
    target_link_libraries(pybrid_buffer_tests pybrid_headers GTest::gtest_main)

    # TCP/Transport tests (requires native_transport.cpp)
    add_executable(pybrid_transport_tests ${CMAKE_CURRENT_SOURCE_DIR}/../tests/test_tcp.cpp)
    target_link_libraries(pybrid_transport_tests pybrid_native_lib GTest::gtest_main)

    if(PYBRID_ENABLE_SANITIZERS)
        target_compile_options(pybrid_buffer_tests PRIVATE -fsanitize=address,undefined -fno-omit-frame-pointer)
        target_link_options(pybrid_buffer_tests PRIVATE -fsanitize=address,undefined)
        target_compile_options(pybrid_transport_tests PRIVATE -fsanitize=address,undefined -fno-omit-frame-pointer)
        target_link_options(pybrid_transport_tests PRIVATE -fsanitize=address,undefined)
    endif()

    # Protobuf tests
    add_executable(pybrid_protobuf_tests ${CMAKE_CURRENT_SOURCE_DIR}/../tests/test_protobuf_parsing.cpp)
    target_link_libraries(pybrid_protobuf_tests pybrid_native_lib GTest::gtest_main)

    if(PYBRID_ENABLE_SANITIZERS)
        target_compile_options(pybrid_protobuf_tests PRIVATE -fsanitize=address,undefined -fno-omit-frame-pointer)
        target_link_options(pybrid_protobuf_tests PRIVATE -fsanitize=address,undefined)
    endif()

    # DataChannel tests
    add_executable(pybrid_data_channel_tests
        ${CMAKE_CURRENT_SOURCE_DIR}/../tests/test_data_channel_base.cpp
        ${CMAKE_CURRENT_SOURCE_DIR}/../tests/test_sample_decoding_data_channel.cpp
    )
    target_link_libraries(pybrid_data_channel_tests pybrid_native_lib GTest::gtest_main)

    if(PYBRID_ENABLE_SANITIZERS)
        target_compile_options(pybrid_data_channel_tests PRIVATE -fsanitize=address,undefined -fno-omit-frame-pointer)
        target_link_options(pybrid_data_channel_tests PRIVATE -fsanitize=address,undefined)
    endif()

    # DataChannel UDP negotiation tests (Sprint 7a — TDD)
    add_executable(pybrid_data_channel_negotiation_tests
        ${CMAKE_CURRENT_SOURCE_DIR}/../tests/test_data_channel_negotiation.cpp
    )
    target_link_libraries(pybrid_data_channel_negotiation_tests pybrid_native_lib GTest::gtest_main)

    if(PYBRID_ENABLE_SANITIZERS)
        target_compile_options(pybrid_data_channel_negotiation_tests PRIVATE -fsanitize=address,undefined -fno-omit-frame-pointer)
        target_link_options(pybrid_data_channel_negotiation_tests PRIVATE -fsanitize=address,undefined)
    endif()

    # ControlChannel tests
    add_executable(pybrid_control_channel_tests ${CMAKE_CURRENT_SOURCE_DIR}/../tests/test_control_channel.cpp)
    target_link_libraries(pybrid_control_channel_tests pybrid_native_lib GTest::gtest_main)

    if(PYBRID_ENABLE_SANITIZERS)
        target_compile_options(pybrid_control_channel_tests PRIVATE -fsanitize=address,undefined -fno-omit-frame-pointer)
        target_link_options(pybrid_control_channel_tests PRIVATE -fsanitize=address,undefined)
    endif()

    # ProxyServer tests
    add_executable(pybrid_proxy_tests ${CMAKE_CURRENT_SOURCE_DIR}/../tests/test_proxy_server.cpp)
    target_link_libraries(pybrid_proxy_tests pybrid_native_lib GTest::gtest_main)

    if(PYBRID_ENABLE_SANITIZERS)
        target_compile_options(pybrid_proxy_tests PRIVATE -fsanitize=address,undefined -fno-omit-frame-pointer)
        target_link_options(pybrid_proxy_tests PRIVATE -fsanitize=address,undefined)
    endif()

    include(GoogleTest)
    gtest_discover_tests(pybrid_buffer_tests)
    gtest_discover_tests(pybrid_transport_tests)
    gtest_discover_tests(pybrid_protobuf_tests)
    gtest_discover_tests(pybrid_data_channel_tests)
    gtest_discover_tests(pybrid_control_channel_tests)
    gtest_discover_tests(pybrid_proxy_tests)
    gtest_discover_tests(pybrid_data_channel_negotiation_tests)
endif()

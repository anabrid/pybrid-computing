cmake_minimum_required(VERSION 3.18)
project(pybrid_computing_native CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

# GCC 15+ compatibility: force include <cstdint> for uintptr_t in abseil-cpp
if(CMAKE_CXX_COMPILER_ID STREQUAL "GNU" AND CMAKE_CXX_COMPILER_VERSION VERSION_GREATER_EQUAL "15")
    add_compile_options("$<$<COMPILE_LANGUAGE:CXX>:-include;cstdint>")
endif()

# Options
option(PYBRID_USE_SYSTEM_GTEST "Use system GoogleTest instead of FetchContent" OFF)
option(PYBRID_BUILD_TESTS "Build C++ tests (only when PYBRID_BUILD_PYTHON is OFF)" OFF)
option(PYBRID_ENABLE_SANITIZERS "Enable address and thread sanitizers" OFF)
option(PYBRID_BUILD_PYTHON "Build Python extension" OFF)

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

# Protobuf + abseil: always build from source via FetchContent.
# Pre-generated .pb.cc/.pb.h files require ABI-compatible protobuf v26.1.
# System abseil versions may be incompatible (e.g. >= 20250512 removed
# absl::if_constexpr), so we always use protobuf's bundled copy.
FetchContent_Declare(
    protobuf
    GIT_REPOSITORY https://github.com/protocolbuffers/protobuf.git
    GIT_TAG        v26.1
    GIT_SHALLOW TRUE
    GIT_PROGRESS TRUE
    GIT_SUBMODULES "third_party/abseil-cpp" "third_party/utf8_range"
    EXCLUDE_FROM_ALL
)
set(protobuf_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(protobuf_MSVC_STATIC_RUNTIME OFF CACHE BOOL "" FORCE)
set(protobuf_INSTALL OFF CACHE BOOL "" FORCE)
set(protobuf_ABSL_PROVIDER "module" CACHE STRING "" FORCE)
set(ABSL_BUILD_TESTING OFF CACHE BOOL "" FORCE)
set(ABSL_ENABLE_INSTALL OFF CACHE BOOL "" FORCE)
FetchContent_MakeAvailable(protobuf)

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

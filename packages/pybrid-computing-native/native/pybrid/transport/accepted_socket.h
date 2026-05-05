#pragma once

#include <cstdint>
#include <string>
#include <utility>

#ifndef ASIO_STANDALONE
#define ASIO_STANDALONE
#endif
#include <asio/ip/tcp.hpp>

#ifndef _WIN32
#include <unistd.h>
#endif

namespace anabrid::pybrid::native {

using NativeSocketHandle = asio::ip::tcp::socket::native_handle_type;

inline NativeSocketHandle invalid_native_socket() {
    return static_cast<NativeSocketHandle>(-1);
}

inline void close_native_socket(NativeSocketHandle handle) {
#ifdef _WIN32
    ::closesocket(handle);
#else
    ::close(handle);
#endif
}

/// Carries a native socket file descriptor and peer info from TCPServer to
/// TCPTransport::from_accepted(). Move-only: the destructor closes the fd
/// unless ownership has been transferred (native_handle reset to invalid).
struct AcceptedSocket {
    NativeSocketHandle native_handle;
    std::string remote_host;
    uint16_t remote_port;

    AcceptedSocket() : native_handle(invalid_native_socket()), remote_port(0) {}
    AcceptedSocket(NativeSocketHandle fd, const std::string& host, uint16_t port)
        : native_handle(fd), remote_host(host), remote_port(port) {}

    ~AcceptedSocket() {
        if (native_handle != invalid_native_socket()) {
            close_native_socket(native_handle);
        }
    }

    // Move-only: copying a raw fd without an ownership protocol causes double-close.
    AcceptedSocket(const AcceptedSocket&) = delete;
    AcceptedSocket& operator=(const AcceptedSocket&) = delete;

    AcceptedSocket(AcceptedSocket&& other) noexcept
        : native_handle(other.native_handle),
          remote_host(std::move(other.remote_host)),
          remote_port(other.remote_port) {
        other.native_handle = invalid_native_socket();
    }

    AcceptedSocket& operator=(AcceptedSocket&& other) noexcept {
        if (this != &other) {
            if (native_handle != invalid_native_socket()) {
                close_native_socket(native_handle);
            }
            native_handle = other.native_handle;
            remote_host = std::move(other.remote_host);
            remote_port = other.remote_port;
            other.native_handle = invalid_native_socket();
        }
        return *this;
    }

    bool is_valid() const { return native_handle != invalid_native_socket(); }
};

}  // namespace anabrid::pybrid::native

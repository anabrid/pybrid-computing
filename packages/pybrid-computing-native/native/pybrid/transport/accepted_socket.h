#pragma once

#include <cstdint>
#include <string>
#include <unistd.h>
#include <utility>

namespace anabrid::pybrid::native {

/// Carries a native socket file descriptor and peer info from TCPServer to
/// TCPTransport::from_accepted(). Move-only: the destructor closes the fd
/// unless ownership has been transferred (native_handle set to -1).
struct AcceptedSocket {
    int native_handle;        ///< Native fd (-1 if not owned)
    std::string remote_host;
    uint16_t remote_port;

    AcceptedSocket() : native_handle(-1), remote_port(0) {}
    AcceptedSocket(int fd, const std::string& host, uint16_t port)
        : native_handle(fd), remote_host(host), remote_port(port) {}

    ~AcceptedSocket() {
        if (native_handle >= 0) {
            ::close(native_handle);
        }
    }

    // Move-only: copying a raw fd without an ownership protocol causes double-close.
    AcceptedSocket(const AcceptedSocket&) = delete;
    AcceptedSocket& operator=(const AcceptedSocket&) = delete;

    AcceptedSocket(AcceptedSocket&& other) noexcept
        : native_handle(other.native_handle),
          remote_host(std::move(other.remote_host)),
          remote_port(other.remote_port) {
        other.native_handle = -1;
    }

    AcceptedSocket& operator=(AcceptedSocket&& other) noexcept {
        if (this != &other) {
            if (native_handle >= 0) {
                ::close(native_handle);
            }
            native_handle = other.native_handle;
            remote_host = std::move(other.remote_host);
            remote_port = other.remote_port;
            other.native_handle = -1;
        }
        return *this;
    }

    bool is_valid() const { return native_handle >= 0; }
};

}  // namespace anabrid::pybrid::native

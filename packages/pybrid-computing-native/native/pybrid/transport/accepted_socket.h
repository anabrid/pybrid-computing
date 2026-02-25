#pragma once

#include <cstdint>
#include <string>

namespace anabrid::pybrid::native {

/// Carries a native socket file descriptor and peer info from TCPServer to
/// TCPTransport::from_accepted(). Transferring via native handle allows the
/// socket to be adopted by a different io_context.
struct AcceptedSocket {
    int native_handle;        ///< Native fd (-1 if invalid)
    std::string remote_host;
    uint16_t remote_port;

    AcceptedSocket() : native_handle(-1), remote_port(0) {}
    AcceptedSocket(int fd, const std::string& host, uint16_t port)
        : native_handle(fd), remote_host(host), remote_port(port) {}

    bool is_valid() const { return native_handle >= 0; }
};

}  // namespace anabrid::pybrid::native

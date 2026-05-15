#pragma once

#include <cstddef>
#include <string>

#ifdef _MSC_VER
// POSIX ssize_t is not available in MSVC; ptrdiff_t is the portable equivalent.
using ssize_t = std::ptrdiff_t;
#else
#include <sys/types.h>
#endif

namespace anabrid::pybrid::native {

/// Standard maximum for UDP to avoid fragmentation (MTU-safe).
/// This is the theoretical max: 65535 - 8 (UDP header) - 20 (IP header).
constexpr size_t MAX_UDP_PACKET_SIZE = 65507;

/// Maximum size of a single varint-framed TCP message.
/// Set to match MAX_UDP_PACKET_SIZE for consistency between transports.
constexpr size_t DEFAULT_TCP_MESSAGE_SIZE = 262084;

constexpr double DEFAULT_TCP_CONNECT_TIMEOUT = 5.0;

/// Only non-error outcomes. Errors throw exceptions (propagated to Python).
enum class RecvStatus {
    Success,      ///< Data received successfully (bytes > 0)
    Timeout,      ///< No data available within timeout
    Disconnected  ///< Peer closed connection (TCP) or socket closed
};

struct RecvResult {
    ssize_t bytes;      ///< Bytes received (>0 on success, 0 otherwise)
    RecvStatus status;  ///< Status code indicating outcome
};

struct UDPStats {
    size_t queue_size;        ///< Current items in receive queue
    size_t packets_received;  ///< Total packets received
    size_t packets_dropped;   ///< Packets dropped due to full queue
    size_t bytes_sent;        ///< Total bytes sent
    size_t bytes_received;    ///< Total bytes received
};

struct TCPStats {
    size_t recv_queue_size;    ///< Current items in receive queue
    size_t send_queue_size;    ///< Current items in send queue
    size_t bytes_sent;         ///< Total bytes sent
    size_t bytes_received;     ///< Total bytes received
    size_t messages_sent;      ///< Total messages sent
    size_t messages_received;  ///< Total messages received
    size_t messages_dropped;   ///< Messages dropped due to full receive queue
};

/**
 * @brief Common transport interface for Python duck-typing.
 *
 * Each transport owns its own io_context and dedicated I/O thread.
 * Users interact ONLY with thread-safe queues via recv()/send() — no
 * direct socket access. recv()/send() are thread-safe for concurrent access.
 */
class ITransport {
public:
    virtual ~ITransport() = default;

    /// Start the io_context thread. Must be called before any I/O operations.
    /// Subsequent calls are no-ops if already running.
    virtual void start() = 0;

    /// Stop the io_context and join the thread. Does NOT drain queues.
    /// Subsequent calls are no-ops if already stopped.
    virtual void stop() = 0;

    virtual bool is_running() const = 0;

    /**
     * @brief Receive data into a caller-provided buffer.
     *
     * Blocks until data is available, timeout expires, or connection closes.
     *
     * @param buffer User-supplied buffer to write data into.
     * @param max_len Maximum bytes to receive (buffer size).
     * @param timeout_secs Timeout in seconds (0 = non-blocking).
     * @return RecvResult with bytes received and status code.
     * @throws std::runtime_error on error conditions.
     */
    virtual RecvResult recv(void* buffer, size_t max_len, double timeout_secs) = 0;

    /**
     * @brief Send data to the connected remote endpoint.
     *
     * For TCP: data is queued for async transmission with varint framing.
     * For UDP: data is sent immediately without framing.
     *
     * @return true if data was sent/queued successfully, false if queue full.
     * @throws std::runtime_error if not connected.
     */
    virtual bool send(const void* data, size_t len) = 0;

    virtual std::string name() const = 0;
    virtual void set_name(const std::string& name) = 0;
};

}  // namespace anabrid::pybrid::native

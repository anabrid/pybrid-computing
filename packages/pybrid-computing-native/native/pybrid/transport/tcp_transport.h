#pragma once

#include <array>
#include <atomic>
#include <condition_variable>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#ifndef ASIO_STANDALONE
#define ASIO_STANDALONE
#endif
#ifndef ASIO_NO_DEPRECATED
#define ASIO_NO_DEPRECATED
#endif

#include <asio.hpp>

#include "../buffer.h"
#include "../buffer_factory.h"
#include "../transport.h"
#include "accepted_socket.h"

namespace anabrid::pybrid::native {

/// Fixed-size queue entry for varint-framed TCP messages.
struct TCPQueueEntry {
    uint32_t data_len;  ///< Actual length of message data
    std::array<uint8_t, DEFAULT_TCP_MESSAGE_SIZE> data;
};

/**
 * @brief TCP transport with varint message framing.
 *
 * A dedicated io_context thread handles all async I/O. A separate send thread
 * drains the lock-free send queue via synchronous asio::write, making it the
 * sole writer on the socket — no cross-thread CAS needed for the send pump.
 * recv() dequeues from the receive queue populated by the io_context thread.
 */
class TCPTransport : public ITransport {
public:
    using Factory = BufferFactory<sizeof(TCPQueueEntry)>;

    explicit TCPTransport(BufferType buffer_type = BufferType::LockFree);

    /// Factory method for server-side connections; adopts an existing native socket.
    /// Caller must call start() after construction.
    static std::unique_ptr<TCPTransport> from_accepted(
        const AcceptedSocket& accepted,
        BufferType buffer_type = BufferType::LockFree);

    ~TCPTransport() override;

    // Non-copyable, non-movable
    TCPTransport(const TCPTransport&) = delete;
    TCPTransport& operator=(const TCPTransport&) = delete;
    TCPTransport(TCPTransport&&) = delete;
    TCPTransport& operator=(TCPTransport&&) = delete;

    void start() override;
    void stop() override;
    bool is_running() const override;
    RecvResult recv(void* buffer, size_t max_len, double timeout_secs) override;
    bool send(const void* data, size_t len) override;
    std::string name() const override;
    void set_name(const std::string& name) override;

    /// @throws std::runtime_error if not running or already connected.
    bool connect(const std::string& host, uint16_t port,
                 double timeout_secs = DEFAULT_TCP_CONNECT_TIMEOUT);

    void disconnect();
    bool is_connected() const;

    /// Block until the send queue is empty and no write is in flight, or timeout.
    bool drain(double timeout_secs);

    std::string remote_host() const;
    uint16_t remote_port() const;
    std::string local_host() const;
    uint16_t local_port() const;

    TCPStats stats() const;
    void reset_stats();

private:
    void start_receive();
    void process_recv_buffer();
    void send_loop();

    asio::io_context io_;
    asio::executor_work_guard<asio::io_context::executor_type> work_guard_;
    std::thread io_thread_;
    std::atomic<bool> running_{false};
    std::atomic<bool> started_once_{false};

    mutable std::mutex socket_mutex_;
    std::unique_ptr<asio::ip::tcp::socket> socket_;
    std::string remote_host_;
    uint16_t remote_port_{0};
    std::atomic<bool> connected_{false};

    std::unique_ptr<IBuffer> recv_queue_;
    std::unique_ptr<IBuffer> send_queue_;

    std::vector<uint8_t> recv_buffer_;
    size_t recv_buffer_used_{0};

    std::thread send_thread_;
    std::mutex send_cv_mutex_;
    std::condition_variable send_cv_;
    std::atomic<bool> sending_{false};

    std::mutex recv_cv_mutex_;
    std::condition_variable recv_cv_;

    std::string name_;
    BufferType buffer_type_;

    std::atomic<size_t> bytes_sent_{0};
    std::atomic<size_t> bytes_received_{0};
    std::atomic<size_t> messages_sent_{0};
    std::atomic<size_t> messages_received_{0};
    std::atomic<size_t> messages_dropped_{0};
};

}  // namespace anabrid::pybrid::native

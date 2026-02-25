#pragma once

#include <array>
#include <atomic>
#include <condition_variable>
#include <memory>
#include <mutex>
#include <string>
#include <thread>

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

namespace anabrid::pybrid::native {

/// Fixed-size queue entry for one UDP datagram.
struct UDPQueueEntry {
    uint16_t data_len;
    std::array<uint8_t, MAX_UDP_PACKET_SIZE> data;
};

/**
 * @brief UDP socket with async receive and synchronous send.
 *
 * A background Asio thread handles all I/O. recv() dequeues from the receive
 * queue; if the queue is full an incoming packet is dropped and tracked in
 * packets_dropped. send()/send_to() execute synchronously on the io_context
 * (non-blocking for reasonable packet sizes).
 */
class UDPSocket : public ITransport {
public:
    using Factory = BufferFactory<sizeof(UDPQueueEntry)>;

    explicit UDPSocket(BufferType buffer_type = BufferType::LockFree);
    ~UDPSocket() override;

    // Non-copyable, non-movable
    UDPSocket(const UDPSocket&) = delete;
    UDPSocket& operator=(const UDPSocket&) = delete;
    UDPSocket(UDPSocket&&) = delete;
    UDPSocket& operator=(UDPSocket&&) = delete;

    void start() override;
    void stop() override;
    bool is_running() const override;
    RecvResult recv(void* buffer, size_t max_len, double timeout_secs) override;
    bool send(const void* data, size_t len) override;
    std::string name() const override;
    void set_name(const std::string& name) override;

    /// @return Actual bound port (useful when port=0 was requested).
    /// @throws std::runtime_error if bind fails or already bound.
    uint16_t bind(uint16_t port = 0);

    void close();
    uint16_t local_port() const;

    /// Set remote endpoint for connected-mode send().
    void connect(const std::string& host, uint16_t port);

    void disconnect();
    bool is_connected() const;

    /// Send without requiring connect(); use explicit destination per packet.
    bool send_to(const void* data, size_t len,
                 const std::string& host, uint16_t port);

    std::string remote_host() const;
    uint16_t remote_port() const;

    UDPStats stats() const;
    void reset_stats();

private:
    void start_receive();
    void handle_receive(const asio::error_code& ec, size_t bytes);

    asio::io_context io_;
    asio::executor_work_guard<asio::io_context::executor_type> work_guard_;
    std::thread io_thread_;
    std::atomic<bool> running_{false};
    std::atomic<bool> started_once_{false};

    mutable std::mutex socket_mutex_;
    std::unique_ptr<asio::ip::udp::socket> socket_;
    asio::ip::udp::endpoint local_endpoint_;
    asio::ip::udp::endpoint remote_endpoint_;
    asio::ip::udp::endpoint sender_endpoint_;  ///< Populated by async_receive_from
    std::atomic<bool> bound_{false};
    std::atomic<bool> connected_{false};

    std::array<uint8_t, MAX_UDP_PACKET_SIZE> recv_buffer_;
    std::unique_ptr<IBuffer> recv_queue_;

    std::mutex recv_cv_mutex_;
    std::condition_variable recv_cv_;

    std::string name_;
    BufferType buffer_type_;

    std::atomic<size_t> packets_received_{0};
    std::atomic<size_t> packets_dropped_{0};
    std::atomic<size_t> bytes_sent_{0};
    std::atomic<size_t> bytes_received_{0};
};

}  // namespace anabrid::pybrid::native

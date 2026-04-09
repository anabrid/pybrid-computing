#include "tcp_transport.h"

#include <algorithm>
#include <chrono>
#include <cstring>
#include <stdexcept>
#include <thread>

#include "../varint.h"

namespace anabrid::pybrid::native {

TCPTransport::TCPTransport(BufferType buffer_type)
    : work_guard_(asio::make_work_guard(io_)),
      recv_queue_(Factory::create(buffer_type)),
      send_queue_(Factory::create(buffer_type)),
      buffer_type_(buffer_type) {
    recv_buffer_.resize(MAX_VARINT_SIZE + DEFAULT_TCP_MESSAGE_SIZE);
}

std::unique_ptr<TCPTransport> TCPTransport::from_accepted(
    const AcceptedSocket& accepted, BufferType buffer_type) {

    if (!accepted.is_valid()) {
        return nullptr;
    }

    auto transport = std::make_unique<TCPTransport>(buffer_type);

    // Adopt the native handle into this transport's io_context.
    transport->socket_ = std::make_unique<asio::ip::tcp::socket>(transport->io_);

    asio::error_code ec;
    transport->socket_->assign(asio::ip::tcp::v4(), accepted.native_handle, ec);
    if (ec) {
        return nullptr;
    }

    transport->socket_->set_option(asio::ip::tcp::no_delay(true), ec);
    transport->socket_->set_option(asio::socket_base::keep_alive(true), ec);

    transport->remote_host_ = accepted.remote_host;
    transport->remote_port_ = accepted.remote_port;
    transport->connected_ = true;

    return transport;
}

TCPTransport::~TCPTransport() { stop(); }

void TCPTransport::start() {
    bool expected = false;
    if (!started_once_.compare_exchange_strong(expected, true)) {
        if (running_) {
            return;
        }
        throw std::runtime_error(
            "TCPTransport cannot be restarted after stopping");
    }

    running_ = true;

    io_thread_ = std::thread([this]() { io_.run(); });
    send_thread_ = std::thread(&TCPTransport::send_loop, this);

    // from_accepted() case: socket is already connected when start() is called.
    if (connected_) {
        asio::post(io_, [this]() { start_receive(); });
    }
}

void TCPTransport::stop() {
    if (!running_.exchange(false)) {
        return;
    }

    work_guard_.reset();
    io_.stop();

    send_cv_.notify_all();

    if (io_thread_.joinable()) {
        io_thread_.join();
    }
    if (send_thread_.joinable()) {
        send_thread_.join();
    }

    recv_cv_.notify_all();

    {
        std::lock_guard<std::mutex> lock(socket_mutex_);
        connected_ = false;
        if (socket_ && socket_->is_open()) {
            asio::error_code ec;
            socket_->shutdown(asio::ip::tcp::socket::shutdown_both, ec);
            socket_->close(ec);
        }
        socket_.reset();
    }
}

bool TCPTransport::is_running() const { return running_; }

RecvResult TCPTransport::recv(void* buffer, size_t max_len, double timeout_secs) {
    TCPQueueEntry entry;

    size_t received = recv_queue_->get(&entry, sizeof(entry));
    if (received == sizeof(entry)) {
        size_t copy_len = std::min(static_cast<size_t>(entry.data_len), max_len);
        std::memcpy(buffer, entry.data.data(), copy_len);
        return {static_cast<ssize_t>(copy_len), RecvStatus::Success};
    }

    if (timeout_secs <= 0.0) {
        return {0, RecvStatus::Timeout};
    }

    if (!connected_) {
        return {0, RecvStatus::Disconnected};
    }

    auto deadline = std::chrono::steady_clock::now() +
                    std::chrono::duration<double>(timeout_secs);

    std::unique_lock<std::mutex> lock(recv_cv_mutex_);
    while (running_ && connected_) {
        received = recv_queue_->get(&entry, sizeof(entry));
        if (received == sizeof(entry)) {
            size_t copy_len = std::min(static_cast<size_t>(entry.data_len), max_len);
            std::memcpy(buffer, entry.data.data(), copy_len);
            return {static_cast<ssize_t>(copy_len), RecvStatus::Success};
        }

        auto status = recv_cv_.wait_until(lock, deadline);
        if (status == std::cv_status::timeout) {
            received = recv_queue_->get(&entry, sizeof(entry));
            if (received == sizeof(entry)) {
                size_t copy_len = std::min(static_cast<size_t>(entry.data_len), max_len);
                std::memcpy(buffer, entry.data.data(), copy_len);
                return {static_cast<ssize_t>(copy_len), RecvStatus::Success};
            }
            return {0, RecvStatus::Timeout};
        }
    }

    return {0, RecvStatus::Disconnected};
}

bool TCPTransport::send(const void* data, size_t len) {
    if (!connected_) {
        throw std::runtime_error("TCP not connected");
    }

    if (len > DEFAULT_TCP_MESSAGE_SIZE) {
        throw std::runtime_error("Message too large: " + std::to_string(len) +
                                 " bytes (max: " +
                                 std::to_string(DEFAULT_TCP_MESSAGE_SIZE) + ")");
    }

    TCPQueueEntry entry;
    entry.data_len = static_cast<uint32_t>(len);
    std::memcpy(entry.data.data(), data, len);

    if (!send_queue_->try_put(sizeof(entry), &entry)) {
        return false;
    }

    send_cv_.notify_one();

    return true;
}

std::string TCPTransport::name() const { return name_; }

void TCPTransport::set_name(const std::string& name) { name_ = name; }

bool TCPTransport::connect(const std::string& host, uint16_t port,
                           double timeout_secs) {
    if (!running_) {
        throw std::runtime_error("Transport must be started before TCP connect");
    }

    if (connected_) {
        throw std::runtime_error("TCP already connected");
    }

    asio::error_code parse_ec;
    auto addr = asio::ip::make_address(host, parse_ec);
    if (parse_ec) {
        throw std::runtime_error("Invalid IP address: " + host);
    }

    std::lock_guard<std::mutex> lock(socket_mutex_);

    socket_ = std::make_unique<asio::ip::tcp::socket>(io_);

    asio::ip::tcp::endpoint endpoint(addr, port);

    std::promise<asio::error_code> connect_promise;
    auto connect_future = connect_promise.get_future();

    asio::post(io_, [this, endpoint, &connect_promise]() {
        socket_->async_connect(
            endpoint,
            [&connect_promise](const asio::error_code& ec) {
                connect_promise.set_value(ec);
            });
    });

    auto timeout = std::chrono::duration<double>(timeout_secs);
    if (connect_future.wait_for(timeout) == std::future_status::timeout) {
        asio::error_code ec;
        socket_->cancel(ec);
        socket_->close(ec);
        socket_.reset();
        return false;
    }

    asio::error_code ec = connect_future.get();
    if (ec) {
        socket_.reset();
        return false;
    }

    socket_->set_option(asio::ip::tcp::no_delay(true));
    socket_->set_option(asio::socket_base::keep_alive(true));

    remote_host_ = host;
    remote_port_ = port;
    connected_ = true;
    recv_buffer_used_ = 0;

    start_receive();

    return true;
}

void TCPTransport::disconnect() {
    std::lock_guard<std::mutex> lock(socket_mutex_);

    connected_ = false;

    if (socket_ && socket_->is_open()) {
        asio::error_code ec;
        socket_->shutdown(asio::ip::tcp::socket::shutdown_both, ec);
        socket_->close(ec);
    }

    socket_.reset();
    recv_cv_.notify_all();
}

bool TCPTransport::is_connected() const { return connected_; }

bool TCPTransport::drain(double timeout_secs) {
    if (!running_) {
        return false;
    }

    auto deadline = std::chrono::steady_clock::now() +
                    std::chrono::duration<double>(timeout_secs);

    while (std::chrono::steady_clock::now() < deadline) {
        if (send_queue_->len() == 0 && !sending_.load(std::memory_order_acquire)) {
            return true;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }

    return send_queue_->len() == 0 && !sending_.load(std::memory_order_acquire);
}

std::string TCPTransport::remote_host() const {
    return remote_host_;
}

uint16_t TCPTransport::remote_port() const {
    return remote_port_;
}

std::string TCPTransport::local_host() const {
    std::lock_guard<std::mutex> lock(socket_mutex_);
    if (!connected_ || !socket_ || !socket_->is_open()) {
        return "";
    }
    asio::error_code ec;
    auto endpoint = socket_->local_endpoint(ec);
    if (ec) {
        return "";
    }
    return endpoint.address().to_string();
}

uint16_t TCPTransport::local_port() const {
    std::lock_guard<std::mutex> lock(socket_mutex_);
    if (!connected_ || !socket_ || !socket_->is_open()) {
        return 0;
    }
    asio::error_code ec;
    auto endpoint = socket_->local_endpoint(ec);
    if (ec) {
        return 0;
    }
    return endpoint.port();
}

TCPStats TCPTransport::stats() const {
    TCPStats s;
    s.recv_queue_size = recv_queue_->len();
    s.send_queue_size = send_queue_->len();
    s.bytes_sent = bytes_sent_.load(std::memory_order_relaxed);
    s.bytes_received = bytes_received_.load(std::memory_order_relaxed);
    s.messages_sent = messages_sent_.load(std::memory_order_relaxed);
    s.messages_received = messages_received_.load(std::memory_order_relaxed);
    s.messages_dropped = messages_dropped_.load(std::memory_order_relaxed);
    return s;
}

void TCPTransport::reset_stats() {
    bytes_sent_.store(0, std::memory_order_relaxed);
    bytes_received_.store(0, std::memory_order_relaxed);
    messages_sent_.store(0, std::memory_order_relaxed);
    messages_received_.store(0, std::memory_order_relaxed);
    messages_dropped_.store(0, std::memory_order_relaxed);
}

void TCPTransport::start_receive() {
    if (!running_ || !connected_ || !socket_ || !socket_->is_open()) {
        return;
    }

    size_t available_space = recv_buffer_.size() - recv_buffer_used_;
    if (available_space == 0) {
        // Expand without cap; system memory is the limit.
        recv_buffer_.resize(recv_buffer_.size() * 2);
        available_space = recv_buffer_.size() - recv_buffer_used_;
    }

    socket_->async_read_some(
        asio::buffer(recv_buffer_.data() + recv_buffer_used_, available_space),
        [this](const asio::error_code& ec, size_t bytes) {
            if (ec) {
                if (ec != asio::error::operation_aborted) {
                    connected_ = false;
                    recv_cv_.notify_all();
                }
                return;
            }

            recv_buffer_used_ += bytes;
            bytes_received_.fetch_add(bytes, std::memory_order_relaxed);

            process_recv_buffer();

            if (running_ && connected_) {
                start_receive();
            }
        });
}

void TCPTransport::process_recv_buffer() {
    while (recv_buffer_used_ > 0) {
        uint64_t msg_len = 0;
        size_t varint_bytes =
            decode_varint(recv_buffer_.data(), recv_buffer_used_, msg_len);

        if (varint_bytes == 0) {
            return;
        }

        if (msg_len > DEFAULT_TCP_MESSAGE_SIZE) {
            // Protocol error: message exceeds queue entry capacity.
            connected_ = false;
            recv_cv_.notify_all();
            return;
        }

        size_t total_msg_size = varint_bytes + msg_len;
        if (recv_buffer_used_ < total_msg_size) {
            return;
        }

        TCPQueueEntry entry;
        entry.data_len = static_cast<uint32_t>(msg_len);

        if (msg_len > entry.data.size()) {
            connected_ = false;
            recv_cv_.notify_all();
            return;
        }

        std::memcpy(entry.data.data(),
                    recv_buffer_.data() + varint_bytes, msg_len);

        if (recv_queue_->try_put(sizeof(entry), &entry)) {
            messages_received_.fetch_add(1, std::memory_order_relaxed);
            recv_cv_.notify_one();
        } else {
            messages_dropped_.fetch_add(1, std::memory_order_relaxed);
        }

        size_t remaining = recv_buffer_used_ - total_msg_size;
        if (remaining > 0) {
            std::memmove(recv_buffer_.data(),
                         recv_buffer_.data() + total_msg_size, remaining);
        }
        recv_buffer_used_ = remaining;
    }
}

void TCPTransport::send_loop() {
    std::vector<uint8_t> wire_buf;

    while (running_.load(std::memory_order_acquire)) {
        TCPQueueEntry entry;
        size_t got = send_queue_->get(&entry, sizeof(entry));

        if (got != sizeof(entry)) {
            std::unique_lock<std::mutex> lock(send_cv_mutex_);
            send_cv_.wait_for(lock, std::chrono::milliseconds(1));
            continue;
        }

        if (!connected_ || !socket_ || !socket_->is_open()) {
            continue;
        }

        wire_buf.resize(MAX_VARINT_SIZE + entry.data_len);
        size_t varint_len = encode_varint(entry.data_len, wire_buf.data());
        std::memcpy(wire_buf.data() + varint_len, entry.data.data(),
                    entry.data_len);
        wire_buf.resize(varint_len + entry.data_len);

        sending_.store(true, std::memory_order_release);
        asio::error_code ec;
        size_t bytes = asio::write(*socket_, asio::buffer(wire_buf), ec);
        sending_.store(false, std::memory_order_release);

        if (ec) {
            if (ec != asio::error::operation_aborted) {
                connected_ = false;
            }
            continue;
        }

        bytes_sent_.fetch_add(bytes, std::memory_order_relaxed);
        messages_sent_.fetch_add(1, std::memory_order_relaxed);
    }
}

}  // namespace anabrid::pybrid::native

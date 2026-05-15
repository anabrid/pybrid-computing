#include "udp_socket.h"

#include <chrono>
#include <cstring>
#include <stdexcept>

namespace anabrid::pybrid::native {

UDPSocket::UDPSocket(BufferType buffer_type)
    : work_guard_(asio::make_work_guard(io_)), recv_queue_(Factory::create(buffer_type)), buffer_type_(buffer_type) {}

UDPSocket::~UDPSocket() {
    stop();
}

void UDPSocket::start() {
    bool expected = false;
    if (!started_once_.compare_exchange_strong(expected, true)) {
        if (running_) {
            return;
        }
        throw std::runtime_error("UDPSocket cannot be restarted after stopping");
    }

    running_ = true;

    {
        std::lock_guard<std::mutex> lock(socket_mutex_);
        if (socket_ && socket_->is_open()) {
            start_receive();
        }
    }

    io_thread_ = std::thread([this]() { io_.run(); });
}

void UDPSocket::stop() {
    if (!running_.exchange(false)) {
        return;
    }

    work_guard_.reset();
    io_.stop();

    if (io_thread_.joinable()) {
        io_thread_.join();
    }

    recv_cv_.notify_all();

    {
        std::lock_guard<std::mutex> lock(socket_mutex_);
        if (socket_ && socket_->is_open()) {
            asio::error_code ec;
            socket_->close(ec);
        }
        socket_.reset();
        bound_ = false;
    }
}

bool UDPSocket::is_running() const {
    return running_;
}

RecvResult UDPSocket::recv(void* buffer, size_t max_len, double timeout_secs) {
    UDPQueueEntry entry;

    size_t received = recv_queue_->get(&entry, sizeof(entry));
    if (received == sizeof(entry)) {
        size_t copy_len = std::min(static_cast<size_t>(entry.data_len), max_len);
        std::memcpy(buffer, entry.data.data(), copy_len);
        return {static_cast<ssize_t>(copy_len), RecvStatus::Success};
    }

    if (timeout_secs <= 0.0) {
        return {0, RecvStatus::Timeout};
    }

    if (!bound_) {
        return {0, RecvStatus::Disconnected};
    }

    auto deadline = std::chrono::steady_clock::now() + std::chrono::duration<double>(timeout_secs);

    std::unique_lock<std::mutex> lock(recv_cv_mutex_);
    while (running_ && bound_) {
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

bool UDPSocket::send(const void* data, size_t len) {
    if (!connected_) {
        throw std::runtime_error("UDP not connected - call connect() first or use send_to()");
    }

    if (!bound_) {
        throw std::runtime_error("UDP socket not bound");
    }

    if (len > MAX_UDP_PACKET_SIZE) {
        throw std::runtime_error(
            "Packet too large: " + std::to_string(len) + " bytes (max: " + std::to_string(MAX_UDP_PACKET_SIZE) + ")");
    }

    std::lock_guard<std::mutex> lock(socket_mutex_);
    if (!socket_ || !socket_->is_open()) {
        throw std::runtime_error("UDP socket not open");
    }

    asio::error_code ec;
    size_t sent = socket_->send_to(asio::buffer(data, len), remote_endpoint_, 0, ec);

    if (ec) {
        throw std::runtime_error("UDP send failed: " + ec.message());
    }

    bytes_sent_.fetch_add(sent, std::memory_order_relaxed);
    return sent == len;
}

std::string UDPSocket::name() const {
    return name_;
}

void UDPSocket::set_name(const std::string& name) {
    name_ = name;
}

uint16_t UDPSocket::bind(uint16_t port) {
    if (bound_) {
        throw std::runtime_error("UDP socket already bound");
    }

    std::lock_guard<std::mutex> lock(socket_mutex_);

    socket_ = std::make_unique<asio::ip::udp::socket>(io_);

    asio::ip::udp::endpoint endpoint(asio::ip::udp::v4(), port);
    socket_->open(endpoint.protocol());

    socket_->set_option(asio::socket_base::reuse_address(true));
    socket_->set_option(asio::socket_base::receive_buffer_size(1024 * 1024));

    socket_->bind(endpoint);

    local_endpoint_ = socket_->local_endpoint();
    bound_ = true;

    if (running_) {
        start_receive();
    }

    return local_endpoint_.port();
}

void UDPSocket::close() {
    std::lock_guard<std::mutex> lock(socket_mutex_);

    bound_ = false;
    connected_ = false;

    if (socket_ && socket_->is_open()) {
        asio::error_code ec;
        socket_->cancel(ec);
        socket_->close(ec);
    }
    socket_.reset();

    recv_cv_.notify_all();
}

uint16_t UDPSocket::local_port() const {
    if (!bound_) {
        return 0;
    }
    return local_endpoint_.port();
}

void UDPSocket::connect(const std::string& host, uint16_t port) {
    asio::error_code ec;
    auto addr = asio::ip::make_address(host, ec);
    if (ec) {
        throw std::runtime_error("Invalid IP address: " + host);
    }

    remote_endpoint_ = asio::ip::udp::endpoint(addr, port);
    connected_ = true;
}

void UDPSocket::disconnect() {
    connected_ = false;
    remote_endpoint_ = asio::ip::udp::endpoint();
}

bool UDPSocket::is_connected() const {
    return connected_;
}

bool UDPSocket::send_to(const void* data, size_t len, const std::string& host, uint16_t port) {
    if (!bound_) {
        throw std::runtime_error("UDP socket not bound");
    }

    if (len > MAX_UDP_PACKET_SIZE) {
        throw std::runtime_error(
            "Packet too large: " + std::to_string(len) + " bytes (max: " + std::to_string(MAX_UDP_PACKET_SIZE) + ")");
    }

    asio::error_code ec;
    auto addr = asio::ip::make_address(host, ec);
    if (ec) {
        throw std::runtime_error("Invalid IP address: " + host);
    }

    asio::ip::udp::endpoint dest(addr, port);

    std::lock_guard<std::mutex> lock(socket_mutex_);
    if (!socket_ || !socket_->is_open()) {
        throw std::runtime_error("UDP socket not open");
    }

    size_t sent = socket_->send_to(asio::buffer(data, len), dest, 0, ec);

    if (ec) {
        throw std::runtime_error("UDP send_to failed: " + ec.message());
    }

    bytes_sent_.fetch_add(sent, std::memory_order_relaxed);
    return sent == len;
}

std::string UDPSocket::remote_host() const {
    if (!connected_) {
        return "";
    }
    return remote_endpoint_.address().to_string();
}

uint16_t UDPSocket::remote_port() const {
    if (!connected_) {
        return 0;
    }
    return remote_endpoint_.port();
}

UDPStats UDPSocket::stats() const {
    UDPStats s;
    s.queue_size = recv_queue_->len();
    s.packets_received = packets_received_.load(std::memory_order_relaxed);
    s.packets_dropped = packets_dropped_.load(std::memory_order_relaxed);
    s.bytes_sent = bytes_sent_.load(std::memory_order_relaxed);
    s.bytes_received = bytes_received_.load(std::memory_order_relaxed);
    return s;
}

void UDPSocket::reset_stats() {
    packets_received_.store(0, std::memory_order_relaxed);
    packets_dropped_.store(0, std::memory_order_relaxed);
    bytes_sent_.store(0, std::memory_order_relaxed);
    bytes_received_.store(0, std::memory_order_relaxed);
}

void UDPSocket::reset_buffers() {
    std::unique_ptr<IBuffer> fresh = Factory::create(buffer_type_);
    std::lock_guard<std::mutex> lock(recv_queue_mutex_);
    recv_queue_ = std::move(fresh);
}

size_t UDPSocket::recv_queue_len() const {
    std::lock_guard<std::mutex> lock(recv_queue_mutex_);
    return recv_queue_->len();
}

void UDPSocket::start_receive() {
    if (!socket_ || !socket_->is_open()) {
        return;
    }

    socket_->async_receive_from(
        asio::buffer(recv_buffer_), sender_endpoint_, [this](const asio::error_code& ec, size_t bytes_received) {
            handle_receive(ec, bytes_received);
        });
}

void UDPSocket::handle_receive(const asio::error_code& ec, size_t bytes_received) {
    if (ec) {
        if (ec == asio::error::operation_aborted) {
            return;
        }
        if (running_ && bound_) {
            start_receive();
        }
        return;
    }

    packets_received_.fetch_add(1, std::memory_order_relaxed);
    bytes_received_.fetch_add(bytes_received, std::memory_order_relaxed);

    UDPQueueEntry entry;
    entry.data_len = static_cast<uint16_t>(std::min(bytes_received, static_cast<size_t>(UINT16_MAX)));
    std::memcpy(entry.data.data(), recv_buffer_.data(), entry.data_len);

    {
        std::lock_guard<std::mutex> lock(recv_queue_mutex_);
        if (!recv_queue_->try_put(sizeof(entry), &entry)) {
            packets_dropped_.fetch_add(1, std::memory_order_relaxed);
        } else {
            recv_cv_.notify_one();
        }
    }

    if (running_ && bound_) {
        start_receive();
    }
}

}  // namespace anabrid::pybrid::native

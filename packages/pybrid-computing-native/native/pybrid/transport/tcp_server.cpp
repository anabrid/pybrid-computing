#include "tcp_server.h"

#include <chrono>
#include <stdexcept>

namespace anabrid::pybrid::native {

TCPServer::TCPServer() : work_guard_(asio::make_work_guard(io_)) {}

TCPServer::~TCPServer() {
    stop();
}

uint16_t TCPServer::bind(uint16_t port) {
    if (acceptor_) {
        throw std::runtime_error("TCPServer already bound");
    }

    acceptor_ = std::make_unique<asio::ip::tcp::acceptor>(io_);

    asio::ip::tcp::endpoint endpoint(asio::ip::tcp::v4(), port);

    asio::error_code ec;
    acceptor_->open(endpoint.protocol(), ec);
    if (ec) {
        throw std::runtime_error("Failed to open acceptor: " + ec.message());
    }

    acceptor_->set_option(asio::socket_base::reuse_address(true), ec);
    if (ec) {
        throw std::runtime_error("Failed to set reuse_address: " + ec.message());
    }

    acceptor_->bind(endpoint, ec);
    if (ec) {
        throw std::runtime_error("Failed to bind: " + ec.message());
    }

    acceptor_->listen(asio::socket_base::max_listen_connections, ec);
    if (ec) {
        throw std::runtime_error("Failed to listen: " + ec.message());
    }

    local_port_ = acceptor_->local_endpoint().port();
    return local_port_;
}

void TCPServer::start() {
    bool expected = false;
    if (!started_once_.compare_exchange_strong(expected, true)) {
        if (running_) {
            return;
        }
        throw std::runtime_error("TCPServer cannot be restarted after stopping");
    }

    if (!acceptor_) {
        throw std::runtime_error("TCPServer must be bound before starting");
    }

    running_ = true;

    do_accept();

    accept_thread_ = std::thread([this]() { io_.run(); });
}

void TCPServer::stop() {
    if (!running_.exchange(false)) {
        return;
    }

    if (acceptor_ && acceptor_->is_open()) {
        asio::error_code ec;
        acceptor_->close(ec);
    }

    work_guard_.reset();
    io_.stop();

    if (accept_thread_.joinable()) {
        accept_thread_.join();
    }

    // Wake any blocked accept() callers before draining, then close all
    // queued server-side fds that were never consumed.
    pending_cv_.notify_all();
    {
        std::lock_guard<std::mutex> lock(pending_mutex_);
        while (!pending_.empty()) {
            pending_.pop();
        }
    }
}

bool TCPServer::is_running() const {
    return running_;
}

uint16_t TCPServer::local_port() const {
    return local_port_;
}

AcceptedSocket TCPServer::accept(double timeout_secs) {
    std::unique_lock<std::mutex> lock(pending_mutex_);

    if (!pending_.empty()) {
        AcceptedSocket accepted = std::move(pending_.front());
        pending_.pop();
        return accepted;
    }

    if (timeout_secs <= 0.0) {
        return AcceptedSocket();
    }

    auto deadline = std::chrono::steady_clock::now() + std::chrono::duration<double>(timeout_secs);

    while (running_) {
        if (!pending_.empty()) {
            AcceptedSocket accepted = std::move(pending_.front());
            pending_.pop();
            return accepted;
        }

        auto status = pending_cv_.wait_until(lock, deadline);
        if (status == std::cv_status::timeout) {
            if (!pending_.empty()) {
                AcceptedSocket accepted = std::move(pending_.front());
                pending_.pop();
                return accepted;
            }
            return AcceptedSocket();
        }
    }

    return AcceptedSocket();
}

void TCPServer::do_accept() {
    if (!running_ || !acceptor_ || !acceptor_->is_open()) {
        return;
    }

    auto socket = std::make_shared<asio::ip::tcp::socket>(io_);

    acceptor_->async_accept(*socket, [this, socket](const asio::error_code& ec) {
        if (ec) {
            if (running_) {
                do_accept();
            }
            return;
        }

        asio::error_code peer_ec;
        auto remote_endpoint = socket->remote_endpoint(peer_ec);

        std::string remote_host;
        uint16_t remote_port = 0;

        if (!peer_ec) {
            remote_host = remote_endpoint.address().to_string();
            remote_port = remote_endpoint.port();
        }

        // Release the native handle so it can be adopted by a different
        // io_context in TCPTransport::from_accepted().
        NativeSocketHandle native_handle = socket->native_handle();
        socket->release();

        {
            std::lock_guard<std::mutex> lock(pending_mutex_);
            pending_.emplace(native_handle, remote_host, remote_port);
        }
        pending_cv_.notify_one();

        if (running_) {
            do_accept();
        }
    });
}

}  // namespace anabrid::pybrid::native

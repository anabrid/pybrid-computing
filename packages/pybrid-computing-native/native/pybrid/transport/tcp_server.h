#pragma once

#include <atomic>
#include <condition_variable>
#include <memory>
#include <mutex>
#include <queue>
#include <string>
#include <thread>

#ifndef ASIO_STANDALONE
#define ASIO_STANDALONE
#endif
#ifndef ASIO_NO_DEPRECATED
#define ASIO_NO_DEPRECATED
#endif

#include <asio.hpp>

#include "accepted_socket.h"

namespace anabrid::pybrid::native {

/**
 * @brief TCP listener that queues accepted connections for synchronous consumption.
 *
 * A background Asio thread accepts connections and pushes AcceptedSocket handles
 * onto an internal queue. accept() dequeues handles, and callers create a
 * TCPTransport via TCPTransport::from_accepted().
 *
 * Sockets are transferred as native file descriptors so they can be adopted
 * by a separate io_context in TCPTransport, working around the Asio restriction
 * that sockets cannot be moved between io_contexts.
 */
class TCPServer {
public:
    TCPServer();
    ~TCPServer();

    // Non-copyable, non-movable
    TCPServer(const TCPServer&) = delete;
    TCPServer& operator=(const TCPServer&) = delete;

    /// @return Actual bound port (useful when port=0 was requested).
    uint16_t bind(uint16_t port = 0);

    void start();
    void stop();

    bool is_running() const;
    uint16_t local_port() const;

    /// Block until a connection is available or timeout expires.
    /// Returns an invalid AcceptedSocket (handle=-1) on timeout.
    AcceptedSocket accept(double timeout_secs);

private:
    void do_accept();

    asio::io_context io_;
    asio::executor_work_guard<asio::io_context::executor_type> work_guard_;
    std::unique_ptr<asio::ip::tcp::acceptor> acceptor_;
    std::thread accept_thread_;
    std::atomic<bool> running_{false};
    std::atomic<bool> started_once_{false};

    uint16_t local_port_{0};

    std::queue<AcceptedSocket> pending_;
    std::mutex pending_mutex_;
    std::condition_variable pending_cv_;
};

}  // namespace anabrid::pybrid::native

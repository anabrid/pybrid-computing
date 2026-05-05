#pragma once

#include <atomic>
#include <chrono>
#include <memory>
#include <optional>
#include <string>

#include "pybrid/proto/main.pb.h"

namespace anabrid::pybrid::native {

// Forward declaration
class TCPTransport;

/// One accepted TCP client connection managed by the ProxyServer.
/// Sessions are queued FIFO; only one is active at a time.
class ClientSession {
public:
    /// UUID is assigned at construction for session tracking.
    /// pending_first_message carries a message already consumed from the
    /// transport during the accept-time peek (anything other than ping).
    explicit ClientSession(std::unique_ptr<TCPTransport> transport,
                           std::optional<pb::MessageV1> pending_first_message = std::nullopt);

    ~ClientSession();

    // Non-copyable, non-movable
    ClientSession(const ClientSession&) = delete;
    ClientSession& operator=(const ClientSession&) = delete;
    ClientSession(ClientSession&&) = delete;
    ClientSession& operator=(ClientSession&&) = delete;

    static size_t alive_count() { return alive_count_.load(std::memory_order_acquire); }
    static size_t alive_peak() { return alive_peak_.load(std::memory_order_acquire); }

    /// Move-out the pending first message (if any). Returns std::nullopt on
    /// subsequent calls; the session never sees the same message twice.
    std::optional<pb::MessageV1> take_pending_first_message();

    /// Stash a message back into the pending slot for the next dispatch pass.
    /// Lock-free: ownership of pending_first_message_ transfers from
    /// server_thread_ to session_thread_ at the deque pop, never concurrently.
    void stash_first_message(pb::MessageV1 msg) {
        pending_first_message_ = std::move(msg);
    }

    std::string session_id_;
    std::string peer_address_;   ///< Set by ProxyServer after construction; for logging only.

    /// True while this is the front-of-queue (active) session.
    std::atomic<bool> active{false};

    bool authenticated_{false};

    /// Set to true when RunStateChangeMessage(DONE) is forwarded; starts the
    /// session timeout countdown.
    std::atomic<bool> done_received{false};

    /// Last protocol activity timestamp.
    std::chrono::steady_clock::time_point last_activity;

    TCPTransport* transport();
    bool is_connected() const;
    bool send(const pb::MessageV1& msg);

private:
    // Test-only: incremented by constructor, decremented by destructor.
    // alive_peak_ records the highest value ever seen; it never decrements,
    // so tests can verify the counter is wired even after all sessions are freed.
    static std::atomic<size_t> alive_count_;
    static std::atomic<size_t> alive_peak_;

    std::unique_ptr<TCPTransport> client_transport_;
    std::optional<pb::MessageV1> pending_first_message_;
};

}  // namespace anabrid::pybrid::native

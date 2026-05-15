#pragma once

#include <atomic>
#include <chrono>
#include <cstdint>
#include <deque>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <thread>

#include "pybrid/proto/main.pb.h"
#include "pybrid/proxy/proxy_backend_handler.h"
#include "pybrid/proxy/proxy_run_coordinator.h"
#include "pybrid/proxy/proxy_session.h"
#include "pybrid/transport/tcp_server.h"
#include "pybrid/transport/tcp_transport.h"

namespace anabrid::pybrid::native {

/// Thin TCP relay between backend REDAC devices and client connections.
///
/// Manages N backends and a FIFO queue of client sessions (one active at a time).
/// Performs no MAC address mapping — entity paths are forwarded as-is.
///
/// All configuration methods must be called before start().
class ProxyServer {
    static constexpr double DEFAULT_SESSION_TIMEOUT_SECS = 10.0;
    static constexpr double ACCEPT_POLL_TIMEOUT_SECS = 0.1;
    static constexpr double RECV_TIMEOUT_SECS = 0.1;
    static constexpr size_t RECV_BUFFER_SIZE = 262144;
    static constexpr double DRAIN_TIMEOUT_SECS = 1.0;
    static constexpr double SESSION_INITIAL_WAIT_SECS = 0.45;
    static constexpr std::chrono::milliseconds WORKER_POLL_INTERVAL{5};
    static constexpr double PEEK_TIMEOUT_SECS = 0.005;
    static constexpr double PRE_ADMIT_RECV_TIMEOUT_SECS = 0.01;

public:
    /// When requires_auth is true, reads PYBRID_AUTHENTICATION from the
    /// environment; throws if absent or empty.
    explicit ProxyServer(bool requires_auth = false);

    /// Calls stop() if still running.
    ~ProxyServer();

    // Non-copyable, non-movable
    ProxyServer(const ProxyServer&) = delete;
    ProxyServer& operator=(const ProxyServer&) = delete;
    ProxyServer(ProxyServer&&) = delete;
    ProxyServer& operator=(ProxyServer&&) = delete;

    /// Connect to a backend device; must be called before start().
    /// If both stack and carrier are provided, injects location metadata into
    /// the cached entity tree for clients to discover physical rack position.
    /// @throws std::runtime_error on connection or extract/reset failure.
    /// @throws std::logic_error if called after start().
    void add_backend(
        const std::string& host,
        uint16_t port,
        std::optional<uint32_t> stack = std::nullopt,
        std::optional<uint32_t> carrier = std::nullopt);

    /// Bind and start accepting client connections.
    /// @throws std::runtime_error if bind fails or no backends were added.
    void start(const std::string& host, uint16_t port);

    void stop();
    bool is_running() const;
    uint16_t local_port() const;

    /// Session idle timeout in seconds after the last DONE state change.
    void set_session_timeout(double secs);

    /// Maximum concurrent sessions. Beyond this, new connections are rejected.
    void set_max_sessions(size_t n);

    void set_debug(bool enabled);

    /// Test-only: force a backend's health directly. Values must match the
    /// BackendHealth enum (0=HEALTHY, 1=REBOOTING, 2=DEAD). Out-of-range
    /// indices are silently ignored.
    void set_backend_health_for_test(size_t index, int new_health);

    /// Test-only: read a backend's health as int. Returns -1 if the index
    /// is out of range.
    int get_backend_health(size_t index) const;

private:
    void server_loop();
    void session_loop();
    void reconnect_loop();
    void poll_queued();
    void run_active_dispatch(ClientSession& session);
    static bool peek_for_ping(TCPTransport& transport, double timeout_secs, std::optional<pb::MessageV1>& out_pending);
    void dispatch_message(ClientSession& session, const pb::MessageV1& msg);

    void handle_reset(ClientSession& client, const pb::MessageV1& msg);
    void handle_extract(ClientSession& client, const pb::MessageV1& msg);
    void handle_config(ClientSession& client, const pb::MessageV1& msg);
    void handle_start_run(ClientSession& client, const pb::MessageV1& msg);
    void handle_auth(ClientSession& client, const pb::MessageV1& msg);
    void handle_calibrate(ClientSession& client, const pb::MessageV1& msg);
    void handle_udp_streaming(ClientSession& client, const pb::MessageV1& msg);
    void handle_ping(ClientSession& client);
    void handle_update(ClientSession& client, const pb::MessageV1& msg);
    void handle_get_overload_status(ClientSession& client, const pb::MessageV1& msg);

    /// True iff every registered backend reports HEALTHY.
    bool all_backends_healthy() const;

    void send_error_to_client(ClientSession& client, const std::string& request_id, const std::string& error_text);

    TCPServer server_;
    std::thread server_thread_;
    std::thread session_thread_;
    std::thread reconnect_thread_;

    /// Protects session_deque_, active_, and active_weak_.
    std::mutex deque_mutex_;
    std::deque<std::shared_ptr<ClientSession>> session_deque_;
    std::shared_ptr<ClientSession> active_;
    std::weak_ptr<ClientSession> active_weak_;

    size_t max_sessions_{8};

    double session_timeout_secs_{DEFAULT_SESSION_TIMEOUT_SECS};

    std::atomic<bool> running_{false};

    /// Shared across all threads to prevent interleaved log lines.
    std::mutex log_mutex_;

    RunCoordinator run_coordinator_;
    ProxyBackendHandler backend_handler_;

    bool requires_auth_{false};
    std::string auth_token_;

    bool debug_{false};
};

}  // namespace anabrid::pybrid::native

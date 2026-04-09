#pragma once

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <functional>
#include <future>
#include <memory>
#include <mutex>
#include <optional>
#include <queue>
#include <shared_mutex>
#include <string>
#include <thread>
#include <unordered_map>
#include <vector>

#include "pybrid/channel/control_channel.h"
#include "pybrid/channel/data_channel.h"
#include "pybrid/proto/main.pb.h"
#include "pybrid/transport/tcp_server.h"
#include "pybrid/transport/tcp_transport.h"

namespace anabrid::pybrid::native {

/// DataChannel subclass that forwards data messages to a callback.
/// set_forward_callback() may be called at any time; it is protected by a
/// shared_mutex so the receive thread and the setter don't race.
class ForwardingDataChannel : public DataChannel {
public:
    using ForwardCallback = std::function<void(pb::MessageV1&)>;

    void set_forward_callback(ForwardCallback cb);

    /// Non-owning pointer to the ProxyServer's shared log mutex.
    void set_log_mutex(std::mutex* mtx);

    /// Must be called before each new run to avoid stale gap warnings.
    void reset_sequence_tracking();

protected:
    void handle_data_message(pb::MessageV1& message) override;

    /// Override: classifies run_state_change as a data message so it is
    /// routed through handle_data_message() → m_forward rather than to
    /// control_response_callback.
    bool is_data_message(const pb::MessageV1& message) const override;

private:
    ForwardCallback m_forward;
    mutable std::shared_mutex m_forward_mutex;
    std::mutex* m_log_mutex{nullptr};

    /// Expected next chunk number per carrier path prefix.
    std::unordered_map<std::string, uint32_t> m_expected_chunk;

    /// Returns the carrier prefix (e.g. "/04-E9-E5-17-E5-68") from a full path.
    static std::string carrier_prefix(const std::string& path);

    void check_sequence(const pb::RunDataMessage& rdm);
};

/// Lifecycle state of a proxied backend device.
/// Values are load-bearing: the test hook and Python binding expose them
/// as integers (0/1/2).
enum class BackendHealth : int {
    HEALTHY = 0,
    REBOOTING = 1,
    DEAD = 2,
};

/// One connected backend device owned by the ProxyServer.
struct BackendDevice {
    std::string host;
    uint16_t port;
    std::unique_ptr<ControlChannel> control;
    std::unique_ptr<ForwardingDataChannel> data_channel;

    std::future<void> data_channel_init_future;

    /// Carrier entity paths discovered via ExtractCommand at add_backend() time.
    /// Used for routing ConfigCommand and ExtractCommand to the correct backend.
    std::vector<std::string> carrier_paths;

    /// Module cached during add_backend(); returned by handle_extract()
    /// without re-querying the backend on each client request.
    pb::Module cached_module;

    /// Physical location of this carrier in the REDAC rack, if provided at
    /// add_backend() time.
    std::optional<uint32_t> location_stack;
    std::optional<uint32_t> location_carrier;

    /// Health state; only written through ProxyServer::set_backend_health()
    /// so callers cannot forget to wake waiters on transitions.
    std::atomic<BackendHealth> health{BackendHealth::HEALTHY};

    BackendDevice() = default;
    BackendDevice(const BackendDevice&) = delete;
    BackendDevice& operator=(const BackendDevice&) = delete;

    // std::atomic is not move-constructible, so we move every other field
    // explicitly and copy the atomic's current value.
    BackendDevice(BackendDevice&& other) noexcept
        : host(std::move(other.host)),
          port(other.port),
          control(std::move(other.control)),
          data_channel(std::move(other.data_channel)),
          data_channel_init_future(std::move(other.data_channel_init_future)),
          carrier_paths(std::move(other.carrier_paths)),
          cached_module(std::move(other.cached_module)),
          location_stack(std::move(other.location_stack)),
          location_carrier(std::move(other.location_carrier)),
          health(other.health.load(std::memory_order_acquire)) {}

    BackendDevice& operator=(BackendDevice&& other) noexcept {
        if (this != &other) {
            host = std::move(other.host);
            port = other.port;
            control = std::move(other.control);
            data_channel = std::move(other.data_channel);
            data_channel_init_future = std::move(other.data_channel_init_future);
            carrier_paths = std::move(other.carrier_paths);
            cached_module = std::move(other.cached_module);
            location_stack = std::move(other.location_stack);
            location_carrier = std::move(other.location_carrier);
            health.store(other.health.load(std::memory_order_acquire),
                         std::memory_order_release);
        }
        return *this;
    }
};

/// One accepted TCP client connection managed by the ProxyServer.
/// Sessions are queued FIFO; only one is active at a time.
class ClientSession {
public:
    /// UUID is assigned at construction for session tracking.
    explicit ClientSession(std::unique_ptr<TCPTransport> transport);

    ~ClientSession();

    // Non-copyable, non-movable
    ClientSession(const ClientSession&) = delete;
    ClientSession& operator=(const ClientSession&) = delete;
    ClientSession(ClientSession&&) = delete;
    ClientSession& operator=(ClientSession&&) = delete;

    std::string session_id_;
    std::string peer_address_;   ///< Set by ProxyServer after construction; for logging only.

    /// True while this is the front-of-queue (active) session.
    std::atomic<bool> active{false};

    bool authenticated_{false};

    /// Set to true when RunStateChangeMessage(DONE) is forwarded; starts the
    /// session timeout countdown.
    std::atomic<bool> done_received{false};

    /// Last protocol activity timestamp. Protected by ProxyServer::session_mutex_.
    std::chrono::steady_clock::time_point last_activity;

    TCPTransport* transport();
    bool is_connected() const;
    bool send(const pb::MessageV1& msg);

private:
    std::unique_ptr<TCPTransport> client_transport_;
};

struct BroadcastResult {
    bool had_error = false;
    std::string error_text;

    // optional - responses only kept when user explicitly asks
    std::vector<pb::MessageV1> responses;
};

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
    static constexpr size_t RECV_BUFFER_SIZE = 65536;
    static constexpr double BACKEND_CONNECT_TIMEOUT_SECS = 10.0;
    static constexpr double BACKEND_REQUEST_TIMEOUT_SECS = 10.0;
    static constexpr double BACKEND_UDP_NEGOTIATION_TIMEOUT_SECS = 2.0;
    static constexpr double DRAIN_TIMEOUT_SECS = 1.0;
    static constexpr double SESSION_INITIAL_WAIT_SECS = 0.45;
    static constexpr std::chrono::milliseconds RECONNECT_POLL_INTERVAL{500};
    static constexpr std::chrono::milliseconds RECONNECT_ATTEMPT_TIMEOUT{5000};

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
    void add_backend(const std::string& host, uint16_t port,
                     std::optional<uint32_t> stack = std::nullopt,
                     std::optional<uint32_t> carrier = std::nullopt);

    /// Collects and groups attached devices by a unique device ID. After calling
    /// this, no more devices may be added.
    void map_backends();

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
    void accept_loop();
    void reconnect_loop();
    void run_session(ClientSession& session);
    void dispatch_message(ClientSession& session, const pb::MessageV1& msg);

    void register_session(const std::string& id,
                          std::unique_lock<std::mutex>& lock);
    void deregister_session(const std::string& id,
                            std::unique_lock<std::mutex>& lock);
    void activate_next_session(std::unique_lock<std::mutex>& lock);

    void install_forward_callbacks(ClientSession& session);
    void clear_forward_callbacks();
    void on_forwarded_run_state(ClientSession& session, BackendDevice& backend, 
        pb::RunState state, std::string reason = "");

    void handle_reset(ClientSession& client, const pb::MessageV1& msg);
    void handle_extract(ClientSession& client, const pb::MessageV1& msg);
    void handle_config(ClientSession& client, const pb::MessageV1& msg);
    void handle_start_run(ClientSession& client, const pb::MessageV1& msg);
    void handle_auth(ClientSession& client, const pb::MessageV1& msg);
    void handle_calibrate(ClientSession& client, const pb::MessageV1& msg);
    void handle_udp_streaming(ClientSession& client, const pb::MessageV1& msg);
    void handle_register_external_entities(ClientSession& client, const pb::MessageV1& msg);
    void handle_update(ClientSession& client, const pb::MessageV1& msg);

    /// Dispatch requests to backends in parallel, returning the first error (if any).
    BroadcastResult broadcast_to_backends(
        std::vector<BackendDevice*> targets,
        std::function<pb::MessageV1(BackendDevice&)> request_factory,
        double timeout_secs = BACKEND_REQUEST_TIMEOUT_SECS,
        bool include_responses = false);

    /// Single writer for BackendDevice::health. Stores the new state under
    /// session_mutex_ and notifies session_cv_ so waiters observe the
    /// transition atomically.
    void set_backend_health(BackendDevice& backend, BackendHealth new_health);

    /// True iff every registered backend reports HEALTHY.
    bool all_backends_healthy() const;

    /// Attempt to bring a backend's control channel back up and rebuild its
    /// UDP data transport. Returns true on success. Exceptions thrown by
    /// the underlying channels are caught and converted to false.
    bool reconnect_backend(BackendDevice& backend,
                           std::chrono::milliseconds timeout);

    BackendDevice* find_backend_for_path(const std::string& entity_path);
    static pb::Entity merge_entity_trees(const std::vector<pb::Entity>& entities);
    void send_error_to_client(
        ClientSession& client,
        const std::string& request_id,
        const std::string& error_text);

    std::mutex backends_mutex_;
    std::vector<BackendDevice> backends_;

    /// Precomputed MAC → BackendDevice* map built in start(). O(1) routing.
    std::unordered_map<std::string, BackendDevice*> path_to_backend_;
    std::unordered_map<std::string, pb::Address> map_backends_;
    bool is_accepting_backends_{true};

    TCPServer server_;
    std::thread accept_thread_;
    std::thread reconnect_thread_;

    std::mutex session_mutex_;
    std::condition_variable session_cv_;
    std::queue<std::string> session_id_queue_;
    std::string active_session_id_;

    /// Raw pointer to the active session for unsolicited message forwarding.
    /// Protected by session_mutex_.
    ClientSession* active_session_{nullptr};

    std::unordered_map<std::string, ClientSession*> session_map_;
    std::vector<std::thread> session_threads_;
    size_t max_sessions_{8};
    std::atomic<size_t> active_session_count_{0};

    double session_timeout_secs_{DEFAULT_SESSION_TIMEOUT_SECS};

    std::atomic<bool> running_{false};

    /// TAKE_OFF counter reset at each StartRunCommand. When it reaches
    /// backends_.size() and sync_callback_ is set, the callback is invoked.
    std::atomic<size_t> take_off_count_{0};

    std::atomic<size_t> done_count_{0};

    /// Monotonically increasing run generation. Stale TAKE_OFF callbacks from
    /// a previous run are discarded by checking against this value.
    std::atomic<uint64_t> run_id_{0};

    bool requires_auth_{false};
    std::string auth_token_;

    bool debug_{false};

    /// Shared across all threads to prevent interleaved log lines.
    std::mutex log_mutex_;
};

}  // namespace anabrid::pybrid::native

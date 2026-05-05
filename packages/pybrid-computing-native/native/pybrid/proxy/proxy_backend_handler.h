#pragma once

#include <atomic>
#include <chrono>
#include <cstddef>
#include <cstdint>
#include <functional>
#include <future>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <unordered_map>
#include <vector>

#include "pybrid/channel/control_channel.h"
#include "pybrid/proto/main.pb.h"
#include "pybrid/proxy/forwarding_data_channel.h"
#include "pybrid/proxy/proxy_session.h"

namespace anabrid::pybrid::native {

class RunCoordinator;

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

    /// Health state; only written through ProxyServer::set_backend_health().
    std::atomic<BackendHealth> health{BackendHealth::HEALTHY};

    BackendDevice() = default;
    BackendDevice(const BackendDevice&) = delete;
    BackendDevice& operator=(const BackendDevice&) = delete;

    BackendDevice(BackendDevice&& other) noexcept;
    BackendDevice& operator=(BackendDevice&& other) noexcept;
};

struct BroadcastResult {
    bool had_error = false;
    std::string error_text;

    // optional - responses only kept when user explicitly asks
    std::vector<pb::MessageV1> responses;
};

/// Owns the proxy server's backend devices and the forward-callback wiring
/// that bridges backend data channels to the active client session.
class ProxyBackendHandler {
public:
    /// Backend protocol timeouts. Public so message handlers can pass an
    /// explicit value where the call site reads more clearly with the constant
    /// named (e.g. unicast send_and_recv) than with a magic number.
    static constexpr double BACKEND_CONNECT_TIMEOUT_SECS = 10.0;
    static constexpr double BACKEND_REQUEST_TIMEOUT_SECS = 10.0;
    static constexpr double BACKEND_UDP_NEGOTIATION_TIMEOUT_SECS = 2.0;
    static constexpr std::chrono::milliseconds RECONNECT_POLL_INTERVAL{500};
    static constexpr std::chrono::milliseconds RECONNECT_ATTEMPT_TIMEOUT{5000};
    static constexpr double PING_PROBE_TIMEOUT_SECS = 2.0;

    using ErrorToClient =
        std::function<void(ClientSession&, const std::string&)>;

    explicit ProxyBackendHandler(std::mutex* log_mutex);
    ~ProxyBackendHandler();

    ProxyBackendHandler(const ProxyBackendHandler&) = delete;
    ProxyBackendHandler& operator=(const ProxyBackendHandler&) = delete;
    ProxyBackendHandler(ProxyBackendHandler&&) = delete;
    ProxyBackendHandler& operator=(ProxyBackendHandler&&) = delete;

    // Pre-start configuration
    void add_backend(const std::string& host, uint16_t port,
                     std::optional<uint32_t> stack,
                     std::optional<uint32_t> carrier);
    void set_debug(bool enabled);

    // Lifecycle
    void start(RunCoordinator& run_coord, ErrorToClient error_cb);
    void stop();
    bool empty() const;
    size_t size() const;

    // Session coordination
    void set_active_session(std::weak_ptr<ClientSession> active);

    // Routing / broadcasting (used by message handlers)
    BackendDevice* find_backend_for_path(const std::string& entity_path);
    BroadcastResult broadcast_to_backends(
        std::vector<BackendDevice*> targets,
        std::function<pb::MessageV1(BackendDevice&)> request_factory,
        double timeout_secs = BACKEND_REQUEST_TIMEOUT_SECS,
        bool include_responses = false);

    /// Snapshot of backend pointers, for handlers that broadcast or iterate.
    /// Returns a fresh vector each call (size is small, <=8 in practice).
    /// Pointer stability is guaranteed for the lifetime of the handler because
    /// `backends_` is immutable after `start()`.
    std::vector<BackendDevice*> targets();
    std::vector<const BackendDevice*> targets() const;
    size_t backend_count() const;

    // Health
    bool all_backends_healthy() const;
    void set_backend_health(BackendDevice& backend, BackendHealth h);

    // Test hooks (called via ProxyServer pass-through)
    void set_backend_health_for_test(size_t index, int new_health);
    int  get_backend_health(size_t index) const;

    /// Reset every backend's data channel sequence tracking.
    void reset_sequence_tracking();

    /// Reset every backend's data-channel buffers.
    void reset_data_channel_buffers();

    /// Reconnect a single backend during an UpdateCommand commit reboot.
    bool reconnect_backend(BackendDevice& backend,
                           std::chrono::milliseconds timeout);

private:
    void install_forward_callbacks();
    void clear_forward_callbacks();

    // Composition / collaborators (set in start())
    RunCoordinator* run_coordinator_{nullptr};
    std::mutex*     log_mutex_{nullptr};
    ErrorToClient   error_to_client_;

    // Backends are owned here.
    mutable std::mutex backends_mutex_;
    std::vector<BackendDevice> backends_;
    std::unordered_map<std::string, BackendDevice*> path_to_backend_;
    bool is_accepting_backends_{true};

    std::atomic<bool> running_{false};

    // Active session for forward-callback target.
    // Captured by value into each forward lambda at install time, so lambdas
    // never race on this field. set_active_session reinstalls the lambdas
    // under active_session_mutex_; the unsolicited-error path reads it under
    // the same mutex.
    std::mutex active_session_mutex_;
    std::weak_ptr<ClientSession> active_session_;

    bool debug_{false};
};

}  // namespace anabrid::pybrid::native

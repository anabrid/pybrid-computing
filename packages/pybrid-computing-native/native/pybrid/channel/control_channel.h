#pragma once

#include <atomic>
#include <cstdint>
#include <functional>
#include <future>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <unordered_map>
#include <vector>

#include "pybrid/proto/main.pb.h"

namespace anabrid::pybrid::native {

// Forward declaration
class TCPTransport;

/// All public methods are thread-safe. Callbacks must be registered before start().
/// The recv thread invokes callbacks and resolves promises; callbacks must be thread-safe.
class ControlChannel {
    static constexpr size_t RECV_BUFFER_SIZE = 65536;
    static constexpr double RECV_TIMEOUT_SECS = 0.1;

public:
    /// @throws std::runtime_error if the connection fails.
    static std::unique_ptr<ControlChannel> create(
        const std::string& host,
        uint16_t port,
        double timeout_secs = 5.0);

    ~ControlChannel();

    // Non-copyable, non-movable
    ControlChannel(const ControlChannel&) = delete;
    ControlChannel& operator=(const ControlChannel&) = delete;
    ControlChannel(ControlChannel&&) = delete;
    ControlChannel& operator=(ControlChannel&&) = delete;

    void start();

    /// Pending send_and_recv() calls will have their promises broken.
    void stop();

    /// Stops only the recv thread, keeping the transport alive for DataChannel TCP fallback.
    void stop_recv_thread();

    std::string remote_host() const;
    uint16_t remote_port() const;
    bool is_connected() const;
    bool is_running() const;

    /// @throws std::runtime_error if the transport is not connected.
    void send(const pb::MessageV1& msg);

    /// @throws std::runtime_error if the transport is not connected.
    void send_raw(const void* data, size_t len);

    /// msg must have a non-empty id field set to a unique UUID.
    /// @throws std::runtime_error if timeout expires or transport disconnects.
    pb::MessageV1 send_and_recv(const pb::MessageV1& msg, double timeout_secs = 5.0);

    pb::Entity describe(double timeout_secs = 5.0);
    pb::ConfigBundle get_config(
        const std::string& entity_path,
        bool recursive = true,
        double timeout_secs = 5.0);
    bool set_config_bundle(const pb::ConfigBundle& bundle, double timeout_secs = 5.0);
    void start_run_request(
        const pb::StartRunCommand& run_command,
        double timeout_secs = 5.0);
    void reset(
        bool keep_calibration = true,
        bool sync = true,
        double timeout_secs = 5.0);
    bool authenticate(const std::string& token, double timeout_secs = 5.0);

    void register_callback(int field_number, std::function<void(pb::MessageV1&)> callback);
    void unregister_callback(int field_number);

    /// Routes a non-data envelope received by DataChannel during TCP fallback.
    void on_tcp_response(std::vector<uint8_t> data);

    TCPTransport* transport();

protected:
    ControlChannel();

    void recv_loop();
    void process_message(pb::MessageV1& msg);
    void dispatch_callback(pb::MessageV1& msg);

    std::unique_ptr<TCPTransport> transport_;

    std::thread recv_thread_;
    std::atomic<bool> running_{false};

    struct PendingRequest {
        std::promise<pb::MessageV1> promise;
    };

    std::mutex pending_mutex_;
    std::unordered_map<std::string, std::shared_ptr<PendingRequest>> pending_requests_;

    std::mutex callback_mutex_;
    std::unordered_map<int, std::function<void(pb::MessageV1&)>> callbacks_;
};

}  // namespace anabrid::pybrid::native

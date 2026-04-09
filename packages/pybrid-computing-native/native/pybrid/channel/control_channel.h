#pragma once

#include <atomic>
#include <chrono>
#include <cstdint>
#include <functional>
#include <future>
#include <memory>
#include <mutex>
#include <optional>
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
    static constexpr double TURN_TIMEOUT_SECS = 5.0;

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

    /// Tear down the active transport and attempt to reconnect to the cached
    /// endpoint. On success, the recv thread is relaunched and previously
    /// registered callbacks remain wired. Returns false on timeout or if
    /// cancel_reconnect() was called before a connection could be established.
    ///
    /// @param interval poll/retry interval between connect attempts
    /// @param timeout  optional absolute deadline; nullopt retries forever
    bool reconnect(
        std::chrono::milliseconds interval = std::chrono::milliseconds{500},
        std::optional<std::chrono::milliseconds> timeout = std::nullopt);

    /// Interrupts any in-flight reconnect() call. Safe to call from any
    /// thread; a subsequent reconnect() re-arms the cancel flag.
    void cancel_reconnect();

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
    pb::MessageV1 send_and_recv(const pb::MessageV1& msg, double timeout_secs = TURN_TIMEOUT_SECS);

    pb::Module extract(
        const std::string& entity_path = "",
        bool recursive = true,
        bool specification = false,
        bool configuration = false,
        bool calibration = false,
        double timeout_secs = TURN_TIMEOUT_SECS);
    void calibrate(const std::string& leader, bool math, bool gain, bool offset, double timeout_secs = TURN_TIMEOUT_SECS);
    bool set_module(const pb::Module& module, double timeout_secs = TURN_TIMEOUT_SECS);
    void start_run_request(
        const pb::StartRunCommand& run_command,
        double timeout_secs = TURN_TIMEOUT_SECS);
    void reset(
        bool keep_calibration = true,
        bool sync = true,
        double timeout_secs = TURN_TIMEOUT_SECS);
    bool authenticate(const std::string& token, double timeout_secs = TURN_TIMEOUT_SECS);

    /// upload commands for OTA updates
    size_t update_begin(size_t new_size, std::string new_sha256,
        double timeout_secs, bool verbose = false);
    void update_write_full(size_t new_size, size_t max_chunk_size, std::vector<uint8_t>& new_data,
        double timeout_secs = TURN_TIMEOUT_SECS, bool verbose = false);
    void update_verify(double timeout_secs = TURN_TIMEOUT_SECS, bool verbose = false);
    void update_commit(double timeout_secs = TURN_TIMEOUT_SECS, bool verbose = false);
    void update_abort(double timeout_secs = TURN_TIMEOUT_SECS);
    void update_simple_response_process(pb::MessageV1&& response);

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

    std::atomic<bool> cancel_reconnect_{false};
    std::atomic<bool> reconnecting_{false};

    struct PendingRequest {
        std::promise<pb::MessageV1> promise;
    };

    std::mutex pending_mutex_;
    std::unordered_map<std::string, std::shared_ptr<PendingRequest>> pending_requests_;

    std::mutex callback_mutex_;
    std::unordered_map<int, std::function<void(pb::MessageV1&)>> callbacks_;
};

}  // namespace anabrid::pybrid::native

#pragma once

#include <atomic>
#include <cstdint>
#include <functional>
#include <memory>
#include <optional>
#include <string>
#include <thread>
#include <vector>

#include "pybrid/proto/main.pb.h"
#include "pybrid/transport.h"

namespace anabrid::pybrid::native {

// Forward declarations
class TCPTransport;
class UDPSocket;
class ControlChannel;

/// Configuration methods and callbacks MUST be set before start() is called.
/// Callbacks are invoked from the receive thread and must be thread-safe.
class DataChannel {
    static constexpr size_t RECV_BUFFER_SIZE = 65536;
    static constexpr double RECV_TIMEOUT_SECS = 0.1;

public:
    virtual ~DataChannel();

    // Non-copyable, non-movable
    DataChannel(const DataChannel&) = delete;
    DataChannel& operator=(const DataChannel&) = delete;
    DataChannel(DataChannel&&) = delete;
    DataChannel& operator=(DataChannel&&) = delete;

    void set_udp_endpoint(const std::string& host, uint16_t port);
    void set_udp_bind_port(uint16_t port);

    /// @param transport Pointer to TCPTransport (must outlive DataChannel).
    void set_tcp_transport(TCPTransport* transport);

    /**
     * @brief Set callback for control responses received during TCP fallback.
     *
     * When UDP streaming is refused, the DataChannel falls back to TCP. The
     * shared TCP stream carries both data messages (handled by DataChannel) and
     * control responses (need routing back to ControlChannel). This callback
     * provides that routing.
     *
     * Invoked from the DataChannel's receive thread — must be thread-safe.
     *
     * @throws std::logic_error if called after start().
     */
    void set_control_response_callback(std::function<void(std::vector<uint8_t>)> callback);

    /**
     * @brief Require UDP transport — throw instead of falling back to TCP.
     *
     * When enabled, start() will throw std::runtime_error if UDP negotiation
     * fails or is refused by the device.
     *
     * @throws std::logic_error if called after start().
     */
    void set_require_udp(bool require);

    /**
     * @brief Set the ControlChannel used for UDP negotiation.
     *
     * When start() is called and no explicit UDP endpoint is configured,
     * sends a UdpDataStreamingCommand through this channel. Must outlive DataChannel.
     *
     * @throws std::logic_error if called after start().
     */
    void set_control_channel(ControlChannel* cc);

    /**
     * @brief Send a UdpDataStreamingCommand and wait for the response.
     *
     * @return true if the device accepted UDP streaming, false if refused.
     * @throws std::runtime_error if no response is received within the timeout.
     */
    bool negotiate_udp(uint16_t local_port);

    /// @throws std::logic_error if called after start().
    void set_negotiation_timeout(double secs);

    void start();
    void stop();
    bool is_running() const;

    /// @return true if UDP was refused and now receiving via TCP.
    bool is_using_tcp_fallback() const;

    std::optional<UDPStats> udp_stats() const;
    void reset_udp_stats();

    pb::RunState current_run_state() const;

    /// @throws std::logic_error if called after start().
    void on_run_state_change(std::function<void(pb::RunState)> callback);

    /// @throws std::logic_error if called after start().
    void on_error(std::function<void(const std::string&)> callback);

    void set_debug(bool enabled) { m_debug = enabled; }

protected:
    DataChannel();

    virtual void handle_data_message(pb::MessageV1& message) = 0;

    /// Override to widen data message classification beyond run_data/run_data_end.
    virtual bool is_data_message(const pb::MessageV1& message) const;

    void update_run_state(pb::RunState new_state);

private:
    std::string m_udp_host;
    uint16_t m_udp_port = 0;
    uint16_t m_udp_bind_port = 0;

    ControlChannel* m_control_channel = nullptr;
    double m_negotiation_timeout = 5.0;

    std::unique_ptr<UDPSocket> m_udp_socket;
    TCPTransport* m_tcp_transport = nullptr;
    std::atomic<bool> m_using_tcp_fallback{false};
    bool m_require_udp{false};

    std::atomic<pb::RunState> m_run_state{pb::NEW};
    std::atomic<bool> m_running{false};

    std::function<void(pb::RunState)> m_state_callback;
    std::function<void(const std::string&)> m_error_callback;
    std::function<void(std::vector<uint8_t>)> m_control_response_callback;

    bool m_debug{false};

    std::thread m_receive_thread;

    void udp_receive_loop();
    void tcp_receive_loop();
    void fallback_to_tcp();

    void throw_if_running(const char* method_name) const;
};

}  // namespace anabrid::pybrid::native

#include "data_channel.h"

#include <iostream>
#include <stdexcept>
#include <vector>

#include "pybrid/channel/control_channel.h"
#include "pybrid/proto/main.pb.h"
#include "pybrid/utils/protobuf_helpers.h"
#include "pybrid/transport/tcp_transport.h"
#include "pybrid/transport/udp_socket.h"
#include "pybrid/utils/uuid.h"

#include "pybrid/utils/protobuf_helpers.h"

namespace anabrid::pybrid::native {

DataChannel::DataChannel() = default;

DataChannel::~DataChannel() {
    // Ensure the receive thread is stopped on destruction to prevent
    // std::terminate from being called by ~std::thread on a joinable thread.
    stop();
}

void DataChannel::set_udp_endpoint(const std::string& host, uint16_t port) {
    m_udp_host = host;
    m_udp_port = port;
}

void DataChannel::set_udp_bind_port(uint16_t port) {
    m_udp_bind_port = port;
}

void DataChannel::set_tcp_transport(TCPTransport* transport) {
    throw_if_running("set_tcp_transport");
    m_tcp_transport = transport;
}

void DataChannel::set_control_response_callback(
    std::function<void(std::vector<uint8_t>)> callback) {
    throw_if_running("set_control_response_callback");
    m_control_response_callback = std::move(callback);
}

void DataChannel::set_require_udp(bool require) {
    throw_if_running("set_require_udp");
    m_require_udp = require;
}

void DataChannel::set_control_channel(ControlChannel* cc) {
    throw_if_running("set_control_channel");
    m_control_channel = cc;
}

void DataChannel::set_negotiation_timeout(double secs) {
    throw_if_running("set_negotiation_timeout");
    m_negotiation_timeout = secs;
}

bool DataChannel::negotiate_udp(uint16_t local_port) {
    if (m_control_channel == nullptr) {
        throw std::logic_error(
            "DataChannel::negotiate_udp(): set_control_channel() must be called first");
    }

    pb::MessageV1 msg;
    msg.set_id(utils::generate_uuid());
    msg.mutable_udp_data_streaming_command()->set_port(
        static_cast<uint32_t>(local_port));

    pb::MessageV1 response =
        m_control_channel->send_and_recv(msg, m_negotiation_timeout);

    if (response.has_success_message()) {
        return true;
    }
    if (response.has_udp_data_streaming_refused_response()) {
        return false;
    }

    throw std::runtime_error(
        "DataChannel::negotiate_udp(): unexpected response type from device");
}

void DataChannel::start() {
    if (m_running.exchange(true, std::memory_order_acq_rel)) {
        return;
    }

    // If a TCP transport was explicitly set but no control channel and no UDP
    // endpoint are configured, go directly to TCP fallback mode ("TCP-only" path).
    if (m_tcp_transport != nullptr && m_control_channel == nullptr
        && m_udp_host.empty() && m_udp_port == 0) {
        m_using_tcp_fallback.store(true, std::memory_order_release);
        m_receive_thread = std::thread(&DataChannel::tcp_receive_loop, this);
        return;
    }

    try {
        m_udp_socket = std::make_unique<UDPSocket>();
        m_udp_socket->bind(m_udp_bind_port);
        m_udp_socket->start();

        // If a ControlChannel is set and no explicit UDP endpoint was configured,
        // perform UDP negotiation: inform the device which local port to stream to.
        if (m_control_channel != nullptr && m_udp_host.empty()) {
            uint16_t bound_port = m_udp_socket->local_port();

            bool udp_accepted = false;
            try {
                udp_accepted = negotiate_udp(bound_port);
            } catch (const std::exception& neg_ex) {
                if (m_require_udp) {
                    m_udp_socket->stop();
                    m_udp_socket.reset();
                    m_running.store(false, std::memory_order_release);
                    throw;
                }
                udp_accepted = false;
                if (m_error_callback) {
                    m_error_callback(
                        "DataChannel::start(): UDP negotiation failed, "
                        "falling back to TCP: " +
                        std::string(neg_ex.what()));
                }
            }

            if (!udp_accepted) {
                m_udp_socket->stop();
                m_udp_socket.reset();

                if (m_require_udp) {
                    m_running.store(false, std::memory_order_release);
                    throw std::runtime_error(
                        "UDP negotiation failed or was refused by device");
                }

                // Stop the ControlChannel's recv thread so it no longer competes
                // for messages on the shared TCP transport. The DataChannel's
                // tcp_receive_loop takes over and routes control responses back
                // via the control_response_callback → on_tcp_response().
                m_control_channel->stop_recv_thread();

                m_tcp_transport = m_control_channel->transport();
                m_using_tcp_fallback.store(true, std::memory_order_release);
                m_receive_thread = std::thread(&DataChannel::tcp_receive_loop, this);
                return;
            }
        }

        m_receive_thread = std::thread(&DataChannel::udp_receive_loop, this);
    } catch (const std::exception& e) {
        m_udp_socket.reset();

        if (m_require_udp) {
            m_running.store(false, std::memory_order_release);
            throw;
        }

        if (m_tcp_transport != nullptr) {
            m_using_tcp_fallback.store(true, std::memory_order_release);
            m_receive_thread = std::thread(&DataChannel::tcp_receive_loop, this);
        } else {
            m_running.store(false, std::memory_order_release);
            if (m_error_callback) {
                m_error_callback("Failed to start DataChannel: " + std::string(e.what()));
            }
        }
    }
}

void DataChannel::stop() {
    m_running.store(false, std::memory_order_release);

    if (m_receive_thread.joinable()) {
        m_receive_thread.join();
    }

    if (m_udp_socket) {
        m_udp_socket->stop();
        m_udp_socket.reset();
    }

    m_using_tcp_fallback.store(false, std::memory_order_release);
}

bool DataChannel::is_running() const {
    return m_running.load(std::memory_order_acquire);
}

bool DataChannel::is_using_tcp_fallback() const {
    return m_using_tcp_fallback.load(std::memory_order_acquire);
}

std::optional<UDPStats> DataChannel::udp_stats() const {
    if (!m_udp_socket) {
        return std::nullopt;
    }
    return m_udp_socket->stats();
}

void DataChannel::reset_udp_stats() {
    if (m_udp_socket) {
        m_udp_socket->reset_stats();
    }
}

pb::RunState DataChannel::current_run_state() const {
    return m_run_state.load(std::memory_order_acquire);
}

void DataChannel::on_run_state_change(std::function<void(pb::RunState)> callback) {
    throw_if_running("on_run_state_change");
    m_state_callback = std::move(callback);
}

void DataChannel::update_run_state(pb::RunState new_state) {
    pb::RunState old_state = m_run_state.exchange(new_state, std::memory_order_acq_rel);
    if (old_state != new_state && m_state_callback) {
        m_state_callback(new_state);
    }
}

void DataChannel::on_error(std::function<void(const std::string&)> callback) {
    throw_if_running("on_error");
    m_error_callback = std::move(callback);
}

void DataChannel::udp_receive_loop() {
    std::vector<uint8_t> buffer(RECV_BUFFER_SIZE);

    while (m_running.load(std::memory_order_acquire)) {
        RecvResult result = m_udp_socket->recv(buffer.data(), buffer.size(), RECV_TIMEOUT_SECS);

        if (result.status == RecvStatus::Timeout) {
            continue;
        }

        if (result.status == RecvStatus::Disconnected) {
            break;
        }

        if (result.status == RecvStatus::Success && result.bytes > 0) {
            // UDP packets may carry either raw MessageV1 or Envelope-wrapped MessageV1.
            // Try Envelope first; if the message has a message_v1 field, extract it.
            // Otherwise fall back to parsing the raw bytes as MessageV1 directly.
            pb::MessageV1 message;
            {
                pb::Envelope envelope;
                if (envelope.ParseFromArray(buffer.data(), static_cast<int>(result.bytes))
                    && envelope.has_message_v1()) {
                    message = envelope.message_v1();
                } else if (!message.ParseFromArray(buffer.data(), static_cast<int>(result.bytes))) {
                    if (m_error_callback) {
                        m_error_callback("Failed to parse UDP message as protobuf");
                    }
                    continue;
                }
            }

            if (message.has_udp_data_streaming_refused_response()) {
                fallback_to_tcp();
                return;
            }

            if (message.has_run_state_change_message()) {
                const pb::RunStateChangeMessage& state_msg = message.run_state_change_message();
                pb::RunState new_state = state_msg.new_();
                update_run_state(new_state);
            }

            if (is_data_message(message)) {
                handle_data_message(message);
            }

            // Forward non-data messages to the ControlChannel so that Python callbacks
            // registered there still fire. In UDP mode, the ControlChannel's recv thread
            // only reads TCP, so we must explicitly forward UDP-delivered messages.
            if (!is_data_message(message) && m_control_response_callback) {
                pb::Envelope env;
                *env.mutable_message_v1() = message;
                std::string serialized;
                env.SerializeToString(&serialized);
                std::vector<uint8_t> bytes(serialized.begin(), serialized.end());
                m_control_response_callback(std::move(bytes));
            }
        }
    }
}

void DataChannel::tcp_receive_loop() {
    std::vector<uint8_t> buffer(RECV_BUFFER_SIZE);

    // Capture TCP transport pointer once at loop start to avoid race condition.
    TCPTransport* transport = m_tcp_transport;
    if (transport == nullptr) {
        if (m_error_callback) {
            m_error_callback("TCP transport not configured for receive loop");
        }
        return;
    }

    while (m_running.load(std::memory_order_acquire)) {
        RecvResult result = transport->recv(buffer.data(), buffer.size(), RECV_TIMEOUT_SECS);

        if (result.status == RecvStatus::Timeout) {
            continue;
        }

        if (result.status == RecvStatus::Disconnected) {
            if (m_error_callback) {
                m_error_callback("TCP connection closed during data streaming");
            }
            break;
        }

        if (result.status == RecvStatus::Success && result.bytes > 0) {
            // TCP transport returns varint-deframed payloads which are
            // serialized pb::Envelope messages (same framing as ControlChannel).
            pb::Envelope envelope;
            if (!envelope.ParseFromArray(buffer.data(), static_cast<int>(result.bytes))) {
                if (m_error_callback) {
                    m_error_callback("Failed to parse TCP Envelope");
                }
                continue;
            }

            if (!envelope.has_message_v1()) {
                continue;
            }

            pb::MessageV1 message = envelope.message_v1();

            if (m_debug) {
                int kind = utils::get_kind_field_number(message);
                std::cerr << "[DataChannel] DEBUG: tcp_receive_loop got kind="
                          << kind
                          << " (data=" << is_data_message(message)
                          << ", state_change=" << message.has_run_state_change_message()
                          << ", run_data=" << message.has_run_data_message()
                          << ", run_data_end=" << message.has_run_data_end_message()
                          << ", bytes=" << result.bytes
                          << ")\n";
            }

            if (message.has_run_state_change_message()) {
                const pb::RunStateChangeMessage& state_msg = message.run_state_change_message();
                pb::RunState new_state = state_msg.new_();
                update_run_state(new_state);
            }

            if (is_data_message(message)) {
                handle_data_message(message);
            } else {
                if (m_control_response_callback) {
                    std::vector<uint8_t> response_data(
                        buffer.begin(),
                        buffer.begin() + static_cast<std::ptrdiff_t>(result.bytes));
                    m_control_response_callback(std::move(response_data));
                }
            }
        }
    }
}

void DataChannel::fallback_to_tcp() {
    if (!m_running.load(std::memory_order_acquire)) {
        return;
    }

    if (m_udp_socket) {
        m_udp_socket->stop();
        m_udp_socket.reset();
    }

    if (m_require_udp) {
        m_running.store(false, std::memory_order_release);
        if (m_error_callback) {
            m_error_callback(
                "UDP streaming refused at runtime and require_udp is set");
        }
        return;
    }

    if (m_tcp_transport == nullptr) {
        m_running.store(false, std::memory_order_release);
        if (m_error_callback) {
            m_error_callback("UDP streaming refused and no TCP fallback configured");
        }
        return;
    }

    m_using_tcp_fallback.store(true, std::memory_order_release);
    tcp_receive_loop();
}

bool DataChannel::is_data_message(const pb::MessageV1& message) const {
    return message.has_run_data_message() ||
           message.has_run_data_end_message();
}

void DataChannel::throw_if_running(const char* method_name) const {
    if (m_running.load(std::memory_order_acquire)) {
        throw std::logic_error(
            std::string(method_name) + "() cannot be called after start()");
    }
}

}  // namespace anabrid::pybrid::native

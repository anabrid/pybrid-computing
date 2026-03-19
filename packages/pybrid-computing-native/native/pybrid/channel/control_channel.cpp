#include "control_channel.h"

#include <chrono>
#include <future>
#include <stdexcept>
#include <vector>

#include "pybrid/proto/main.pb.h"
#include "pybrid/transport/tcp_transport.h"
#include "pybrid/utils/protobuf_helpers.h"
#include "pybrid/utils/uuid.h"

namespace anabrid::pybrid::native {

ControlChannel::ControlChannel() = default;

ControlChannel::~ControlChannel() {
    stop();
}

std::unique_ptr<ControlChannel> ControlChannel::create(
    const std::string& host,
    uint16_t port,
    double timeout_secs)
{
    auto channel = std::unique_ptr<ControlChannel>(new ControlChannel());

    channel->transport_ = std::make_unique<TCPTransport>();
    channel->transport_->start();

    bool connected = channel->transport_->connect(host, port, timeout_secs);
    if (!connected) {
        channel->transport_->stop();
        throw std::runtime_error(
            "ControlChannel::create(): failed to connect to " + host + ":" +
            std::to_string(port));
    }

    return channel;
}

void ControlChannel::start() {
    bool expected = false;
    if (!running_.compare_exchange_strong(expected, true, std::memory_order_acq_rel)) {
        return;
    }

    recv_thread_ = std::thread(&ControlChannel::recv_loop, this);
}

void ControlChannel::stop_recv_thread() {
    running_.store(false, std::memory_order_release);

    if (recv_thread_.joinable()) {
        recv_thread_.join();
    }

    // Pending requests are NOT failed here because the DataChannel
    // will route responses back via on_tcp_response() → process_message().
}

void ControlChannel::stop() {
    stop_recv_thread();

    // Fail any still-pending promises so callers don't block forever.
    {
        std::lock_guard<std::mutex> lock(pending_mutex_);
        for (auto& kv : pending_requests_) {
            try {
                kv.second->promise.set_exception(
                    std::make_exception_ptr(std::runtime_error(
                        "ControlChannel stopped while request was pending")));
            } catch (const std::future_error&) {
                // Promise may already have been satisfied — ignore.
            }
        }
        pending_requests_.clear();
    }

    if (transport_) {
        transport_->stop();
    }
}

std::string ControlChannel::remote_host() const {
    if (!transport_) return {};
    return transport_->remote_host();
}

uint16_t ControlChannel::remote_port() const {
    if (!transport_) return 0;
    return transport_->remote_port();
}

bool ControlChannel::is_connected() const {
    if (!transport_) return false;
    return transport_->is_connected();
}

bool ControlChannel::is_running() const {
    return running_.load(std::memory_order_acquire);
}

void ControlChannel::send(const pb::MessageV1& msg) {
    pb::Envelope envelope;
    *envelope.mutable_message_v1() = msg;

    std::string serialized;
    if (!envelope.SerializeToString(&serialized)) {
        throw std::runtime_error("ControlChannel::send(): failed to serialize Envelope");
    }

    if (!transport_->send(serialized.data(), serialized.size())) {
        throw std::runtime_error("ControlChannel::send(): transport send failed");
    }
}

void ControlChannel::send_raw(const void* data, size_t len) {
    if (!transport_->send(data, len)) {
        throw std::runtime_error("ControlChannel::send_raw(): transport send failed");
    }
}

pb::MessageV1 ControlChannel::send_and_recv(const pb::MessageV1& msg, double timeout_secs) {
    const std::string& id = msg.id();
    if (id.empty()) {
        throw std::runtime_error(
            "ControlChannel::send_and_recv(): msg.id() must be non-empty");
    }

    // Register the pending request before sending to avoid a race where the
    // response arrives before we've inserted into pending_requests_.
    auto pending = std::make_shared<PendingRequest>();
    std::future<pb::MessageV1> future = pending->promise.get_future();

    {
        std::lock_guard<std::mutex> lock(pending_mutex_);
        pending_requests_.emplace(id, pending);
    }

    try {
        send(msg);
    } catch (...) {
        std::lock_guard<std::mutex> lock(pending_mutex_);
        pending_requests_.erase(id);
        throw;
    }

    auto timeout = std::chrono::duration<double>(timeout_secs);
    std::future_status status = future.wait_for(timeout);

    if (status == std::future_status::timeout) {
        std::lock_guard<std::mutex> lock(pending_mutex_);
        pending_requests_.erase(id);
        throw std::runtime_error(
            "ControlChannel::send_and_recv(): timeout waiting for response to id=" + id);
    }

    return future.get();
}

void ControlChannel::register_callback(
    int field_number,
    std::function<void(pb::MessageV1&)> callback)
{
    std::lock_guard<std::mutex> lock(callback_mutex_);
    callbacks_[field_number] = std::move(callback);
}

void ControlChannel::unregister_callback(int field_number) {
    std::lock_guard<std::mutex> lock(callback_mutex_);
    callbacks_.erase(field_number);
}

void ControlChannel::on_tcp_response(std::vector<uint8_t> data) {
    pb::Envelope envelope;
    if (!envelope.ParseFromArray(data.data(), static_cast<int>(data.size()))) {
        return;
    }

    if (!envelope.has_message_v1()) {
        return;
    }

    pb::MessageV1 msg = envelope.message_v1();
    process_message(msg);
}

TCPTransport* ControlChannel::transport() {
    return transport_.get();
}

void ControlChannel::recv_loop() {
    std::vector<uint8_t> buffer(RECV_BUFFER_SIZE);

    while (running_.load(std::memory_order_acquire)) {
        RecvResult result =
            transport_->recv(buffer.data(), buffer.size(), RECV_TIMEOUT_SECS);

        if (result.status == RecvStatus::Timeout) {
            continue;
        }

        if (result.status == RecvStatus::Disconnected) {
            running_.store(false, std::memory_order_release);

            std::lock_guard<std::mutex> lock(pending_mutex_);
            for (auto& kv : pending_requests_) {
                try {
                    kv.second->promise.set_exception(
                        std::make_exception_ptr(std::runtime_error(
                            "ControlChannel: TCP connection closed")));
                } catch (const std::future_error&) {
                    // Already satisfied — ignore.
                }
            }
            pending_requests_.clear();
            break;
        }

        if (result.status == RecvStatus::Success && result.bytes > 0) {
            pb::Envelope envelope;
            if (!envelope.ParseFromArray(
                    buffer.data(), static_cast<int>(result.bytes))) {
                continue;
            }

            if (!envelope.has_message_v1()) {
                continue;
            }

            pb::MessageV1 msg = envelope.message_v1();
            process_message(msg);
        }
    }
}

void ControlChannel::process_message(pb::MessageV1& msg) {
    const std::string& id = msg.id();

    if (id.empty()) {
        dispatch_callback(msg);
        return;
    }

    {
        std::lock_guard<std::mutex> lock(pending_mutex_);
        auto it = pending_requests_.find(id);
        if (it != pending_requests_.end()) {
            auto pending = it->second;
            pending_requests_.erase(it);
            // Lock released before setting value to minimise contention.
            try {
                pending->promise.set_value(std::move(msg));
            } catch (const std::future_error&) {
                // Promise already satisfied (e.g., stop() was called) — ignore.
            }
            return;
        }
    }

    // Non-empty id, no pending request — inbound request from peer.
    dispatch_callback(msg);
}

void ControlChannel::dispatch_callback(pb::MessageV1& msg) {
    int field_number = utils::get_kind_field_number(msg);
    if (field_number == 0) {
        return;
    }

    std::lock_guard<std::mutex> lock(callback_mutex_);
    auto it = callbacks_.find(field_number);
    if (it != callbacks_.end() && it->second) {
        it->second(msg);
    }
}

pb::Module ControlChannel::extract(
    const std::string& entity_path,
    bool recursive, bool specification, bool configuration,
    bool calibration, double timeout_secs) {
    pb::MessageV1 msg;
    msg.set_id(utils::generate_uuid());
    auto* cmd = msg.mutable_extract_command();
    if (!entity_path.empty()) {
        cmd->mutable_entity()->set_path(entity_path);
    }
    cmd->set_recursive(recursive);
    cmd->set_specification(specification);
    cmd->set_configuration(configuration);
    cmd->set_calibration(calibration);

    pb::MessageV1 response = send_and_recv(msg, timeout_secs);

    if (response.has_error_message()) {
        throw std::runtime_error(
            "ControlChannel::extract(): device returned error: " +
            response.error_message().description());
    }

    return response.extract_response().module();
}

void ControlChannel::calibrate(const std::string& leader, bool math, bool gain,
    bool offset, double timeout_secs){
    pb::MessageV1 msg;
    msg.set_id(utils::generate_uuid());
    auto calibration_cmd = msg.mutable_calibration_command();
    auto calibration_config = calibration_cmd->mutable_config();

    if (!leader.empty()) {
        calibration_config->mutable_leader()->set_path(leader);
    }
    calibration_config->set_math(math ? pb::CalibrationConfig_Kind_Enabled :
        pb::CalibrationConfig_Kind_Disabled);
    calibration_config->set_gain(gain ? pb::CalibrationConfig_Kind_Enabled :
        pb::CalibrationConfig_Kind_Disabled);
    calibration_config->set_offset(offset ? pb::CalibrationConfig_Kind_Enabled :
        pb::CalibrationConfig_Kind_Disabled);

    pb::MessageV1 response = send_and_recv(msg, timeout_secs);

    if (response.has_error_message()) {
        throw std::runtime_error(
            "ControlChannel::calibrate(): device returned error: " +
            response.error_message().description());
    }
}

bool ControlChannel::set_module(const pb::Module& module, double timeout_secs) {
    pb::MessageV1 msg;
    msg.set_id(utils::generate_uuid());

    pb::ConfigCommand* config_command = msg.mutable_config_command();
    config_command->mutable_module()->CopyFrom(module);
    config_command->set_reset_before(true);

    pb::MessageV1 response = send_and_recv(msg, timeout_secs);

    if (response.has_error_message()) {
        throw std::runtime_error(response.error_message().description());
    }
    return true;
}

void ControlChannel::start_run_request(
    const pb::StartRunCommand& run_command,
    double timeout_secs)
{
    pb::MessageV1 msg;
    msg.set_id(utils::generate_uuid());
    msg.mutable_start_run_command()->CopyFrom(run_command);

    pb::MessageV1 response = send_and_recv(msg, timeout_secs);

    if (response.has_error_message()) {
        throw std::runtime_error(
            "ControlChannel::start_run_request(): device returned error: " +
            response.error_message().description());
    }
}

void ControlChannel::reset(bool keep_calibration, bool sync, double timeout_secs) {
    pb::MessageV1 msg;
    msg.set_id(utils::generate_uuid());

    pb::ResetCommand* reset_command = msg.mutable_reset_command();
    reset_command->set_keep_calibration(keep_calibration);
    reset_command->set_sync(sync);

    pb::MessageV1 response = send_and_recv(msg, timeout_secs);

    if (response.has_error_message()) {
        throw std::runtime_error(
            "ControlChannel::reset(): device returned error: " +
            response.error_message().description());
    }
}

bool ControlChannel::authenticate(const std::string& token, double timeout_secs) {
    pb::MessageV1 msg;
    msg.set_id(utils::generate_uuid());

    pb::AuthRequest* auth_request = msg.mutable_auth_request();
    auth_request->mutable_bearer()->set_token(token);

    pb::MessageV1 response = send_and_recv(msg, timeout_secs);

    if (response.has_error_message()) {
        throw std::runtime_error(response.error_message().description());
    }
    return true;
}

}  // namespace anabrid::pybrid::native

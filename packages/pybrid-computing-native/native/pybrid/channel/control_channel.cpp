#include "control_channel.h"

#include <algorithm>
#include <chrono>
#include <cstdio>
#include <future>
#include <mutex>
#include <stdexcept>
#include <thread>
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
    double timeout_secs,
    std::uint32_t max_busy_wait_secs)
{
    auto channel = std::unique_ptr<ControlChannel>(new ControlChannel());
    channel->max_busy_wait_secs_ = max_busy_wait_secs;

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

void ControlChannel::cancel_send_and_recv() {
    {
        std::lock_guard<std::mutex> lk(busy_wait_mutex_);
        busy_wait_cancelled_.store(true, std::memory_order_release);
    }
    busy_wait_cv_.notify_all();
}

std::uint32_t ControlChannel::max_busy_wait_secs() const {
    return max_busy_wait_secs_;
}

void ControlChannel::set_max_busy_wait_secs(std::uint32_t secs) {
    max_busy_wait_secs_ = secs;
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

    // DataChannel routes responses back via on_tcp_response().
}

void ControlChannel::stop() {
    stop_recv_thread();

    {
        std::lock_guard<std::mutex> lock(pending_mutex_);
        for (auto& kv : pending_requests_) {
            try {
                kv.second->promise.set_exception(
                    std::make_exception_ptr(std::runtime_error(
                        "ControlChannel stopped while request was pending")));
            } catch (const std::future_error&) {
                }
        }
        pending_requests_.clear();
    }
    {
        std::lock_guard<std::mutex> lk(ping_mutex_);
        if (pending_ping_) {
            try { pending_ping_->set_exception(
                std::make_exception_ptr(std::runtime_error("stopped"))); }
            catch (const std::future_error&) {}
            pending_ping_.reset();
        }
    }

    if (transport_) {
        transport_->stop();
    }
}

bool ControlChannel::reconnect(
    std::chrono::milliseconds interval,
    std::optional<std::chrono::milliseconds> timeout)
{
    if (!transport_) return false;

    cancel_reconnect_.store(false, std::memory_order_release);
    reconnecting_.store(true, std::memory_order_release);

    running_.store(false, std::memory_order_release);
    if (recv_thread_.joinable()) recv_thread_.join();

    {
        std::lock_guard<std::mutex> lock(pending_mutex_);
        for (auto& kv : pending_requests_) {
            try {
                kv.second->promise.set_exception(
                    std::make_exception_ptr(std::runtime_error("reconnecting")));
            } catch (const std::future_error&) {}
        }
        pending_requests_.clear();
    }
    {
        std::lock_guard<std::mutex> lk(ping_mutex_);
        if (pending_ping_) {
            try { pending_ping_->set_exception(
                std::make_exception_ptr(std::runtime_error("reconnecting"))); }
            catch (const std::future_error&) {}
            pending_ping_.reset();
        }
    }

    auto host = transport_->remote_host();
    auto port = transport_->remote_port();
    transport_->disconnect();

    if (interval < std::chrono::milliseconds{10})
        interval = std::chrono::milliseconds{10};

    const auto deadline = timeout
        ? std::chrono::steady_clock::now() + *timeout
        : std::chrono::steady_clock::time_point::max();

    while (!cancel_reconnect_.load(std::memory_order_acquire)) {
        if (std::chrono::steady_clock::now() >= deadline) {
            reconnecting_.store(false, std::memory_order_release);
            return false;
        }

        double attempt_secs = std::chrono::duration<double>(interval).count();
        try {
            if (transport_->connect(host, port, attempt_secs)) {
                start();
                reconnecting_.store(false, std::memory_order_release);
                return true;
            }
        } catch (...) {}

        std::this_thread::sleep_for(interval);
    }

    reconnecting_.store(false, std::memory_order_release);
    return false;
}

void ControlChannel::cancel_reconnect() {
    cancel_reconnect_.store(true, std::memory_order_release);
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
    if (reconnecting_.load(std::memory_order_acquire))
        throw std::runtime_error("ControlChannel::send(): reconnect in progress");
    if (!is_connected())
        throw std::runtime_error("ControlChannel::send(): not connected");

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
    if (reconnecting_.load(std::memory_order_acquire))
        throw std::runtime_error("ControlChannel::send_raw(): reconnect in progress");
    if (!is_connected())
        throw std::runtime_error("ControlChannel::send_raw(): not connected");

    if (!transport_->send(data, len)) {
        throw std::runtime_error("ControlChannel::send_raw(): transport send failed");
    }
}

namespace {

// Poll interval between busy-retry attempts. The condition variable can wake
// earlier via cancel_send_and_recv().
constexpr std::chrono::seconds kBusyRetryPollInterval{2};

}  // namespace

pb::MessageV1 ControlChannel::send_and_recv(const pb::MessageV1& msg, double timeout_secs) {
    if (reconnecting_.load(std::memory_order_acquire))
        throw std::runtime_error("ControlChannel::send_and_recv(): reconnect in progress");
    if (!is_connected())
        throw std::runtime_error("ControlChannel::send_and_recv(): not connected");

    if (msg.id().empty()) {
        throw std::runtime_error(
            "ControlChannel::send_and_recv(): msg.id() must be non-empty");
    }

    // One caller owns the busy-wait flag at a time; resetting on entry is
    // sufficient because there is no defined semantics for concurrent callers.
    busy_wait_cancelled_.store(false, std::memory_order_release);

    pb::MessageV1 current_msg = msg;
    const auto busy_loop_start = std::chrono::steady_clock::now();
    const auto max_wait = std::chrono::seconds(max_busy_wait_secs_);

    while (true) {
        const std::string id = current_msg.id();

        auto pending = std::make_shared<PendingRequest>();
        std::future<pb::MessageV1> future = pending->promise.get_future();

        {
            std::lock_guard<std::mutex> lock(pending_mutex_);
            pending_requests_.emplace(id, pending);
        }

        try {
            send(current_msg);
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

        pb::MessageV1 response = future.get();

        if (!response.has_busy_response()) {
            return response;
        }

        // Busy: sleep on the condvar up to the poll interval, or wake early
        // on cancel. Sleeping past the deadline is bounded by clamping the
        // wait to the remaining budget; the cap is then enforced once after
        // the sleep (the first iteration always gets one sleep before any
        // cap check, which is the intended behaviour).
        {
            std::unique_lock<std::mutex> lk(busy_wait_mutex_);
            auto elapsed = std::chrono::steady_clock::now() - busy_loop_start;
            auto remaining = (elapsed >= max_wait)
                ? std::chrono::steady_clock::duration::zero()
                : (max_wait - elapsed);
            auto sleep_for = std::min<std::chrono::steady_clock::duration>(
                kBusyRetryPollInterval, remaining);
            busy_wait_cv_.wait_for(lk, sleep_for, [this] {
                return busy_wait_cancelled_.load(std::memory_order_acquire);
            });
        }

        if (busy_wait_cancelled_.load(std::memory_order_acquire)) {
            throw std::runtime_error(
                "ControlChannel::send_and_recv(): busy wait cancelled");
        }

        auto elapsed = std::chrono::steady_clock::now() - busy_loop_start;
        if (elapsed >= max_wait) {
            // Report elapsed with 0.1 s resolution so a fast trip never shows
            // "0s". std::to_string(double) gives 6 decimals; format manually.
            auto elapsed_ms =
                std::chrono::duration_cast<std::chrono::milliseconds>(elapsed).count();
            char buf[32];
            std::snprintf(buf, sizeof(buf), "%lld.%01lld",
                static_cast<long long>(elapsed_ms / 1000),
                static_cast<long long>((elapsed_ms % 1000) / 100));
            throw std::runtime_error(
                "Device busy for " + std::string(buf) +
                "s, exceeded max wait of " +
                std::to_string(max_busy_wait_secs_) + "s");
        }

        // Regenerate the id so the retry is correlated independently from the
        // just-resolved busy reply.
        current_msg.set_id(utils::generate_uuid());
    }
}

void ControlChannel::ping(double timeout_secs) {
    if (reconnecting_.load(std::memory_order_acquire))
        throw std::runtime_error("ControlChannel::ping(): reconnect in progress");
    if (!is_connected())
        throw std::runtime_error("ControlChannel::ping(): not connected");

    auto pending = std::make_shared<std::promise<void>>();
    std::future<void> future = pending->get_future();

    {
        std::lock_guard<std::mutex> lk(ping_mutex_);
        pending_ping_ = pending;
    }

    pb::Envelope envelope;
    envelope.mutable_generic()->mutable_ping_command();

    std::string serialized;
    if (!envelope.SerializeToString(&serialized)) {
        std::lock_guard<std::mutex> lk(ping_mutex_);
        pending_ping_.reset();
        throw std::runtime_error("ControlChannel::ping(): failed to serialize");
    }

    if (!transport_->send(serialized.data(), serialized.size())) {
        std::lock_guard<std::mutex> lk(ping_mutex_);
        pending_ping_.reset();
        throw std::runtime_error("ControlChannel::ping(): transport send failed");
    }

    auto timeout = std::chrono::duration<double>(timeout_secs);
    if (future.wait_for(timeout) == std::future_status::timeout) {
        std::lock_guard<std::mutex> lk(ping_mutex_);
        pending_ping_.reset();
        throw std::runtime_error("ControlChannel::ping(): timeout");
    }
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

void ControlChannel::clear_callbacks() {
    std::lock_guard<std::mutex> lock(callback_mutex_);
    callbacks_.clear();
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
            transport_->disconnect();

            {
                std::lock_guard<std::mutex> lock(pending_mutex_);
                for (auto& kv : pending_requests_) {
                    try {
                        kv.second->promise.set_exception(
                            std::make_exception_ptr(std::runtime_error(
                                "ControlChannel: TCP connection closed")));
                    } catch (const std::future_error&) {}
                }
                pending_requests_.clear();
            }
            {
                std::lock_guard<std::mutex> lk(ping_mutex_);
                if (pending_ping_) {
                    try { pending_ping_->set_exception(
                        std::make_exception_ptr(std::runtime_error(
                            "ControlChannel: TCP connection closed"))); }
                    catch (const std::future_error&) {}
                    pending_ping_.reset();
                }
            }
            break;
        }

        if (result.status == RecvStatus::Success && result.bytes > 0) {
            pb::Envelope envelope;
            if (!envelope.ParseFromArray(
                    buffer.data(), static_cast<int>(result.bytes))) {
                continue;
            }

            if (envelope.has_generic()) {
                const auto& generic = envelope.generic();
                if (generic.has_ping_response()) {
                    std::lock_guard<std::mutex> lk(ping_mutex_);
                    if (pending_ping_) {
                        try { pending_ping_->set_value(); }
                        catch (const std::future_error&) {}
                        pending_ping_.reset();
                    }
                }
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
            try {
                pending->promise.set_value(std::move(msg));
            } catch (const std::future_error&) {}
            return;
        }
    }

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

void ControlChannel::reset(
    bool keep_calibration,
    bool sync,
    bool overload_reset,
    bool circuit_reset,
    double timeout_secs) {
    pb::MessageV1 msg;
    msg.set_id(utils::generate_uuid());

    pb::ResetCommand* reset_command = msg.mutable_reset_command();
    reset_command->set_keep_calibration(keep_calibration);
    reset_command->set_sync(sync);
    reset_command->set_overload_reset(overload_reset);
    reset_command->set_circuit_reset(circuit_reset);

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

bool ControlChannel::overload_status_request(pb::OverloadStatus& ol_status, double timeout_secs)
{
    pb::MessageV1 msg;
    msg.set_id(utils::generate_uuid());
    msg.mutable_get_overload_status_command();

    pb::MessageV1 response = send_and_recv(msg, timeout_secs);

    if (response.has_error_message())
    {
        throw std::runtime_error(response.error_message().description());
    }
    
    if (!response.has_get_overload_status_response())
    {
        throw std::runtime_error("Unexpected answer message to GetOverloadStatusRequest");
    }

    // retrieve elements
    const pb::GetOverloadStatusResponse& res = response.get_overload_status_response();

    if (!res.has_status())
    {
        throw std::runtime_error("Status element not set in overload status response.");
    }

    const pb::OverloadStatus& status = res.status();
    ol_status.CopyFrom(status);
    return status.global_overload();
}

size_t ControlChannel::update_begin(size_t new_size, std::string new_sha256,
    double timeout_secs, bool verbose)
{
    if (verbose) {
        char line[128];
        int pos = snprintf(line, sizeof(line), "\rBeginning firmware update...");
        while (pos < 100) line[pos++] = ' ';
        line[pos] = '\0';
        fwrite(line, 1, pos, stderr);
        fflush(stderr);
    }

    pb::MessageV1 msg;
    msg.set_id(utils::generate_uuid());

    pb::UpdateCommand* update_cmd = msg.mutable_update_command();
    auto begin_cmd = update_cmd->mutable_begin();

    begin_cmd->set_size(new_size);
    begin_cmd->set_hash(new_sha256);

    pb::MessageV1 response = send_and_recv(msg, timeout_secs);

    if (response.has_error_message()) {
        throw std::runtime_error(response.error_message().description());
    }

    if (!response.has_update_response()) {
        throw std::runtime_error("No update response received");
    }

    if(response.update_response().has_failure()) {
        throw std::runtime_error(response.update_response().failure().reason());
    }

    assert(response.update_response().has_ack());
    return response.update_response().ack().chunk_size();
}

void ControlChannel::update_write_full(size_t new_size, size_t max_chunk_size,
    std::vector<uint8_t>& new_data, double timeout_secs, bool verbose)
{
    const size_t total_chunks = (new_size + max_chunk_size - 1) / max_chunk_size;
    size_t chunk_idx = 0;
    constexpr int bar_width = 40;

    for(size_t offset = 0; offset < new_size; offset += max_chunk_size)
    {
        const size_t chunk_size = std::min(
            max_chunk_size,
            new_size - offset
        );

        // send one chunk of data
        pb::MessageV1 msg;
        msg.set_id(utils::generate_uuid());

        pb::UpdateCommand* update_cmd = msg.mutable_update_command();
        auto chunk_cmd = update_cmd->mutable_write();

        std::string buf;
        buf.resize(chunk_size);
        memcpy(buf.data(), new_data.data() + offset, chunk_size);

        chunk_cmd->set_data(buf);
        chunk_cmd->set_offset(static_cast<uint64_t>(offset));

        update_simple_response_process(send_and_recv(msg, timeout_secs));

        ++chunk_idx;
        if (verbose) {
            const float progress = static_cast<float>(chunk_idx) / static_cast<float>(total_chunks);
            const int filled = static_cast<int>(progress * bar_width);
            char line[128];
            int pos = snprintf(line, sizeof(line), "\rUploading firmware: [");
            for (int i = 0; i < bar_width; ++i) {
                line[pos++] = (i < filled ? '#' : '.');
            }
            pos += snprintf(line + pos, sizeof(line) - pos,
                "] %3d%% (%zu/%zu chunks)",
                static_cast<int>(progress * 100), chunk_idx, total_chunks);
            // pad to fixed width so shorter subsequent lines fully overwrite
            while (pos < 100) line[pos++] = ' ';
            line[pos] = '\0';
            fwrite(line, 1, pos, stderr);
            fflush(stderr);
        }
    }
}

void ControlChannel::update_verify(double timeout_secs, bool verbose)
{
    if (verbose) {
        char line[128];
        int pos = snprintf(line, sizeof(line), "\rVerifying firmware...");
        while (pos < 100) line[pos++] = ' ';
        line[pos] = '\0';
        fwrite(line, 1, pos, stderr);
        fflush(stderr);
    }

    pb::MessageV1 msg;
    msg.set_id(utils::generate_uuid());

    pb::UpdateCommand* update_cmd = msg.mutable_update_command();
    update_cmd->mutable_verify();

    // device compares hash and returns success or failure
    update_simple_response_process(send_and_recv(msg, timeout_secs));
}

void ControlChannel::update_commit(double timeout_secs, bool verbose)
{
    if (verbose) {
        char line[128];
        int pos = snprintf(line, sizeof(line), "\rCommitting firmware update...");
        while (pos < 100) line[pos++] = ' ';
        line[pos] = '\0';
        fwrite(line, 1, pos, stderr);
        fflush(stderr);
    }

    pb::MessageV1 msg;
    msg.set_id(utils::generate_uuid());

    pb::UpdateCommand* update_cmd = msg.mutable_update_command();
    update_cmd->mutable_commit();

    update_simple_response_process(send_and_recv(msg, timeout_secs));

    if (verbose) {
        char line[128];
        int pos = snprintf(line, sizeof(line), "\rFirmware update complete.");
        while (pos < 100) line[pos++] = ' ';
        line[pos++] = '\n';
        line[pos] = '\0';
        fwrite(line, 1, pos, stderr);
    }
}

void ControlChannel::update_abort(double timeout_secs)
{
    pb::MessageV1 msg;
    msg.set_id(utils::generate_uuid());

    pb::UpdateCommand* update_cmd = msg.mutable_update_command();
    update_cmd->mutable_abort();

    // device compares hash and returns success or failure
    update_simple_response_process(send_and_recv(msg, timeout_secs));
}

void ControlChannel::update_simple_response_process(pb::MessageV1&& response)
{
    if (response.has_error_message()) {
        throw std::runtime_error(response.error_message().description());
    }

    if (!response.has_update_response()) {
        throw std::runtime_error("No update response received");
    }

    if (response.update_response().has_failure()) {
        throw std::runtime_error(response.update_response().failure().reason());
    }
}


}  // namespace anabrid::pybrid::native

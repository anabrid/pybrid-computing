#include "pybrid/proxy/proxy_session.h"

#include <chrono>
#include <stdexcept>
#include <string>
#include <utility>

#include "pybrid/transport/tcp_transport.h"
#include "pybrid/utils/protobuf_helpers.h"
#include "pybrid/utils/uuid.h"

namespace anabrid::pybrid::native {

// Test-only: ODR definitions for alive_count_ and alive_peak_.
std::atomic<size_t> ClientSession::alive_count_{0};
std::atomic<size_t> ClientSession::alive_peak_{0};

ClientSession::ClientSession(std::unique_ptr<TCPTransport> transport,
                             std::optional<pb::MessageV1> pending_first_message)
    : session_id_(utils::generate_uuid()),
      last_activity(std::chrono::steady_clock::now()),
      client_transport_(std::move(transport)),
      pending_first_message_(std::move(pending_first_message)) {
    if (!client_transport_) {
        throw std::invalid_argument("ClientSession: transport must not be null");
    }
    // Test-only: track live instances and record the maximum ever seen.
    size_t current = alive_count_.fetch_add(1, std::memory_order_relaxed) + 1;
    size_t peak = alive_peak_.load(std::memory_order_relaxed);
    while (current > peak &&
           !alive_peak_.compare_exchange_weak(peak, current,
                                              std::memory_order_relaxed)) {}
}

ClientSession::~ClientSession() {
    // Test-only: track live instances.
    alive_count_.fetch_sub(1, std::memory_order_relaxed);
}

std::optional<pb::MessageV1> ClientSession::take_pending_first_message() {
    std::optional<pb::MessageV1> out;
    out.swap(pending_first_message_);
    return out;
}

TCPTransport* ClientSession::transport() {
    return client_transport_.get();
}

bool ClientSession::is_connected() const {
    return client_transport_ && client_transport_->is_connected();
}

bool ClientSession::send(const pb::MessageV1& msg) {
    std::string bytes = utils::serialize_message(msg);
    if (bytes.empty()) return false;
    if (!is_connected()) return false;
    try {
        return client_transport_->send(bytes.data(), bytes.size());
    } catch (const std::runtime_error&) {
        // TOCTOU: client disconnected between is_connected() and send().
        return false;
    }
}

}  // namespace anabrid::pybrid::native

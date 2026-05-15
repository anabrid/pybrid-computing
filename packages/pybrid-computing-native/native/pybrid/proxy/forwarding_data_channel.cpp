#include "pybrid/proxy/forwarding_data_channel.h"

#include <cstdint>
#include <iostream>
#include <utility>

namespace anabrid::pybrid::native {

void ForwardingDataChannel::set_forward_callback(ForwardCallback cb) {
    std::unique_lock lock(m_forward_mutex);
    m_forward = std::move(cb);
}

void ForwardingDataChannel::set_log_mutex(std::mutex* mtx) {
    m_log_mutex = mtx;
}

void ForwardingDataChannel::reset_sequence_tracking() {
    m_expected_chunk.clear();
}

void ForwardingDataChannel::handle_data_message(pb::MessageV1& message) {
    if (message.has_run_data_message()) {
        check_sequence(message.run_data_message());
    }

    std::shared_lock lock(m_forward_mutex);
    if (m_forward) {
        m_forward(message);
    }
}

bool ForwardingDataChannel::is_data_message(const pb::MessageV1& message) const {
    return message.has_run_data_message() || message.has_run_data_end_message() ||
           message.has_run_state_change_message();
}

std::string ForwardingDataChannel::carrier_prefix(const std::string& path) {
    if (path.empty()) return path;
    // Skip leading '/'
    size_t start = (path[0] == '/') ? 1 : 0;
    size_t pos = path.find('/', start);
    if (pos == std::string::npos) return path;
    return path.substr(0, pos);
}

void ForwardingDataChannel::check_sequence(const pb::RunDataMessage& rdm) {
    if (!rdm.has_run() || !rdm.has_entity()) return;

    uint32_t chunk = rdm.run().chunk();
    const std::string& full_path = rdm.entity().path();
    std::string carrier = carrier_prefix(full_path);

    auto it = m_expected_chunk.find(carrier);
    if (it == m_expected_chunk.end()) {
        // First chunk for this carrier in this run; initialise.
        m_expected_chunk[carrier] = chunk + 1;
        return;
    }

    uint32_t expected = it->second;
    if (chunk != expected) {
        int64_t gap = static_cast<int64_t>(chunk) - static_cast<int64_t>(expected);
        if (m_log_mutex) {
            std::lock_guard<std::mutex> lock(*m_log_mutex);
            std::cerr << "[ProxyServer] WARNING: Sequence gap on carrier " << carrier << ": expected chunk " << expected
                      << ", got " << chunk << " (gap=" << gap << ")\n";
        } else {
            std::cerr << "[ProxyServer] WARNING: Sequence gap on carrier " << carrier << ": expected chunk " << expected
                      << ", got " << chunk << " (gap=" << gap << ")\n";
        }
    }
    it->second = chunk + 1;
}

}  // namespace anabrid::pybrid::native

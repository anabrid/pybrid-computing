#pragma once

#include <cstdint>
#include <functional>
#include <mutex>
#include <shared_mutex>
#include <string>
#include <unordered_map>

#include "pybrid/channel/data_channel.h"
#include "pybrid/proto/main.pb.h"

namespace anabrid::pybrid::native {

/// DataChannel subclass that forwards data messages to a callback.
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

}  // namespace anabrid::pybrid::native

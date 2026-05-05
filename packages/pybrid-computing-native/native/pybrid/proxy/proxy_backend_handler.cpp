#include "pybrid/proxy/proxy_backend_handler.h"

#include <future>
#include <iostream>
#include <stdexcept>
#include <utility>

#include "pybrid/proto/main.pb.h"
#include "pybrid/proxy/proxy_run_coordinator.h"
#include "pybrid/transport/tcp_transport.h"

namespace anabrid::pybrid::native {

BackendDevice::BackendDevice(BackendDevice&& other) noexcept
    : host(std::move(other.host)),
      port(other.port),
      control(std::move(other.control)),
      data_channel(std::move(other.data_channel)),
      data_channel_init_future(std::move(other.data_channel_init_future)),
      carrier_paths(std::move(other.carrier_paths)),
      cached_module(std::move(other.cached_module)),
      location_stack(std::move(other.location_stack)),
      location_carrier(std::move(other.location_carrier)),
      health(other.health.load(std::memory_order_acquire)) {}

BackendDevice& BackendDevice::operator=(BackendDevice&& other) noexcept {
    if (this != &other) {
        host = std::move(other.host);
        port = other.port;
        control = std::move(other.control);
        data_channel = std::move(other.data_channel);
        data_channel_init_future = std::move(other.data_channel_init_future);
        carrier_paths = std::move(other.carrier_paths);
        cached_module = std::move(other.cached_module);
        location_stack = std::move(other.location_stack);
        location_carrier = std::move(other.location_carrier);
        health.store(other.health.load(std::memory_order_acquire),
                     std::memory_order_release);
    }
    return *this;
}

ProxyBackendHandler::ProxyBackendHandler(std::mutex* log_mutex)
    : log_mutex_(log_mutex) {}
ProxyBackendHandler::~ProxyBackendHandler() = default;

void ProxyBackendHandler::add_backend(const std::string& host,
                                      uint16_t port,
                                      std::optional<uint32_t> stack,
                                      std::optional<uint32_t> carrier) {
    if (!is_accepting_backends_) {
        throw std::logic_error(
            "Backends have been finalized, no more changes are permitted.");
    }

    auto control = ControlChannel::create(host, port, BACKEND_CONNECT_TIMEOUT_SECS);
    control->start();

    pb::Module module = control->extract(
        /*entity_path=*/"", /*recursive=*/true, /*specification=*/true,
        /*configuration=*/false, /*calibration=*/false,
        BACKEND_REQUEST_TIMEOUT_SECS);

    std::vector<std::string> carrier_paths;
    for (const auto& item : module.items()) {
        if (item.has_entity_specification()) {
            const auto& entity = item.entity_specification().entity();
            if (!entity.id().empty()) {
                std::string mac = entity.id();
                if (!mac.empty() && mac[0] == '/') {
                    mac = mac.substr(1);
                }
                carrier_paths.push_back(mac);
            }
        }
    }

    {
        // pre-start: no other thread is logging yet
        std::cerr << "[ProxyServer] Backend " << host << ":" << port
                  << " — carrier: "
                  << (carrier_paths.empty() ? "(none)" : carrier_paths[0]);
        if (stack.has_value() && carrier.has_value()) {
            std::cerr << " (stack " << stack.value()
                      << ", carrier " << carrier.value() << ")";
        }
        std::cerr << "\n";
    }

    control->reset(/*keep_calibration=*/true, /*sync=*/true,
                   BACKEND_REQUEST_TIMEOUT_SECS);

    auto data_channel = std::make_unique<ForwardingDataChannel>();
    if (log_mutex_) {
        data_channel->set_log_mutex(log_mutex_);
    }
    if (debug_) {
        data_channel->set_debug(true);
    }

    // The proxy prefers UDP for device→proxy data streaming but accepts
    // a device-initiated refusal and falls back to TCP on the shared
    // ControlChannel transport. When that fallback engages the data
    // channel owns the recv side, so route control-shaped responses
    // (anything that is not a data/state message) back into the control
    // channel so pending send_and_recv() calls resolve.
    data_channel->set_control_channel(control.get());
    data_channel->set_require_udp(false);
    ControlChannel* control_ptr = control.get();
    data_channel->set_control_response_callback(
        [control_ptr](std::vector<uint8_t> data) {
            control_ptr->on_tcp_response(std::move(data));
        });

    data_channel->start();
    std::future<void> init_future = std::async(
        std::launch::deferred,
        []() { /* no-op: start() already completed */ });

    {
        std::lock_guard<std::mutex> lock(backends_mutex_);
        BackendDevice dev;
        dev.host = host;
        dev.port = port;
        dev.control = std::move(control);
        dev.data_channel = std::move(data_channel);
        dev.data_channel_init_future = std::move(init_future);
        dev.carrier_paths = std::move(carrier_paths);
        dev.cached_module = std::move(module);
        dev.location_stack = stack;
        dev.location_carrier = carrier;
        if (stack.has_value() && carrier.has_value()) {
            for (auto& item : *dev.cached_module.mutable_items()) {
                if (item.has_entity_specification()) {
                    auto* loc = item.mutable_entity_specification()
                                    ->mutable_entity()
                                    ->mutable_location_v0();
                    loc->set_stack(stack.value());
                    loc->set_carrier(carrier.value());
                }
            }
        }
        backends_.push_back(std::move(dev));
    }
}

void ProxyBackendHandler::set_debug(bool enabled) {
    debug_ = enabled;
}

void ProxyBackendHandler::start(RunCoordinator& run_coord,
                                ErrorToClient error_cb) {
    run_coordinator_ = &run_coord;
    error_to_client_ = std::move(error_cb);

    // Order matters: register the unsolicited error callback BEFORE building
    // path_to_backend_ — a future edit to the callback might consult the map.
    for (auto& backend : backends_) {
        ControlChannel* ctrl = backend.control.get();
        if (!ctrl) continue;

        ctrl->register_callback(
            pb::MessageV1::kErrorMessageFieldNumber,
            [this](pb::MessageV1& msg) {
                if (!running_.load(std::memory_order_acquire)) return;
                if (debug_) {
                    std::cerr << "[ProxyServer] DEBUG: Error from device: "
                              << msg.error_message().description() << "\n";
                }
                std::shared_ptr<ClientSession> active;
                {
                    std::lock_guard<std::mutex> lock(active_session_mutex_);
                    active = active_session_.lock();
                }
                if (active && active->active.load()) {
                    if (!active->send(msg)) {
                        std::cerr << "[ProxyServer] WARNING: Failed to forward "
                                  << "ErrorMessage to client\n";
                    }
                }
            });
    }

    is_accepting_backends_ = false;
    path_to_backend_.clear();
    {
        std::lock_guard<std::mutex> lock(backends_mutex_);
        for (auto& backend : backends_) {
            for (const auto& path : backend.carrier_paths) {
                path_to_backend_[path] = &backend;
            }
        }
    }

    running_.store(true, std::memory_order_release);
}

void ProxyBackendHandler::stop() {
    std::vector<BackendDevice*> snapshot;
    {
        std::lock_guard<std::mutex> lock(backends_mutex_);
        snapshot.reserve(backends_.size());
        for (auto& backend : backends_) snapshot.push_back(&backend);
    }

    for (auto* backend : snapshot) {
        if (backend->control) {
            backend->control->cancel_reconnect();
        }
    }

    for (auto* backend : snapshot) {
        if (backend->control) {
            backend->control->stop();
        }
    }

    for (auto* backend : snapshot) {
        if (backend->data_channel_init_future.valid()) {
            backend->data_channel_init_future.wait_for(
                std::chrono::duration<double>(
                    BACKEND_UDP_NEGOTIATION_TIMEOUT_SECS + 1.0));
        }
    }

    for (auto* backend : snapshot) {
        if (backend->data_channel) {
            backend->data_channel->stop();
        }
    }

    path_to_backend_.clear();
    running_.store(false, std::memory_order_release);
}

bool ProxyBackendHandler::empty() const {
    std::lock_guard<std::mutex> lock(backends_mutex_);
    return backends_.empty();
}

size_t ProxyBackendHandler::size() const {
    std::lock_guard<std::mutex> lock(backends_mutex_);
    return backends_.size();
}

void ProxyBackendHandler::set_active_session(std::weak_ptr<ClientSession> active) {
    std::lock_guard<std::mutex> lock(active_session_mutex_);
    active_session_ = std::move(active);
    if (active_session_.lock()) {
        install_forward_callbacks();
    } else {
        clear_forward_callbacks();
    }
}

BackendDevice* ProxyBackendHandler::find_backend_for_path(
    const std::string& entity_path) {
    if (entity_path.empty()) return nullptr;

    // Extract the MAC address: first segment before any '/'.
    // Strip optional leading '/' first.
    size_t start = (entity_path[0] == '/') ? 1 : 0;
    auto slash_pos = entity_path.find('/', start);
    std::string mac = (slash_pos != std::string::npos)
        ? entity_path.substr(start, slash_pos - start)
        : entity_path.substr(start);

    // carrier_paths are stored without leading '/'.
    auto it = path_to_backend_.find(mac);
    if (it != path_to_backend_.end()) return it->second;
    return nullptr;
}

BroadcastResult ProxyBackendHandler::broadcast_to_backends(
    std::vector<BackendDevice*> targets,
    std::function<pb::MessageV1(BackendDevice&)> request_factory,
    double timeout_secs,
    bool include_responses) {

    struct BackendTask {
        BackendDevice* backend;
        std::future<pb::MessageV1> future;
    };

    std::vector<BackendTask> tasks;
    tasks.reserve(targets.size());

    BroadcastResult result;
    for (auto* backend : targets) {
        if (!backend->control || !backend->control->is_connected()) {
            result.had_error = true;
            result.error_text = "Backend " + backend->host + " not connected!";
            continue;
        }

        // Capture by value: request built eagerly so the factory doesn't
        // need to be thread-safe.
        pb::MessageV1 req = request_factory(*backend);
        auto* ctrl = backend->control.get();
        tasks.push_back({backend, std::async(std::launch::async,
            [ctrl, r = std::move(req), timeout_secs]() mutable {
                return ctrl->send_and_recv(r, timeout_secs);
            })});
    }

    for (auto& task : tasks) {
        try {
            pb::MessageV1 resp = task.future.get();

            if (include_responses)
                result.responses.emplace_back(resp);

            if (resp.has_error_message() && !result.had_error) {
                result.had_error = true;
                result.error_text = resp.error_message().description();
            }
        } catch (const std::exception& e) {
            if (!result.had_error) {
                result.had_error = true;
                result.error_text = e.what();
            }
        }
    }

    return result;
}

std::vector<BackendDevice*> ProxyBackendHandler::targets() {
    std::lock_guard<std::mutex> lock(backends_mutex_);
    std::vector<BackendDevice*> snapshot;
    snapshot.reserve(backends_.size());
    for (auto& backend : backends_) snapshot.push_back(&backend);
    return snapshot;
}

std::vector<const BackendDevice*> ProxyBackendHandler::targets() const {
    std::lock_guard<std::mutex> lock(backends_mutex_);
    std::vector<const BackendDevice*> snapshot;
    snapshot.reserve(backends_.size());
    for (auto const& backend : backends_) snapshot.push_back(&backend);
    return snapshot;
}

size_t ProxyBackendHandler::backend_count() const {
    std::lock_guard<std::mutex> lock(backends_mutex_);
    return backends_.size();
}

bool ProxyBackendHandler::all_backends_healthy() const {
    std::lock_guard<std::mutex> lock(backends_mutex_);
    for (auto const& backend : backends_) {
        if (backend.health.load(std::memory_order_acquire) !=
            BackendHealth::HEALTHY) {
            return false;
        }
    }
    return true;
}

void ProxyBackendHandler::set_backend_health(BackendDevice& backend,
                                             BackendHealth h) {
    backend.health.store(h, std::memory_order_release);
}

void ProxyBackendHandler::set_backend_health_for_test(size_t index,
                                                      int new_health) {
    std::lock_guard<std::mutex> lock(backends_mutex_);
    if (index >= backends_.size()) {
        throw std::out_of_range("backend index out of range");
    }
    set_backend_health(backends_[index],
                       static_cast<BackendHealth>(new_health));
}

int ProxyBackendHandler::get_backend_health(size_t index) const {
    std::lock_guard<std::mutex> lock(backends_mutex_);
    if (index >= backends_.size()) {
        throw std::out_of_range("backend index out of range");
    }
    return static_cast<int>(
        backends_[index].health.load(std::memory_order_acquire));
}

void ProxyBackendHandler::reset_sequence_tracking() {
    std::lock_guard<std::mutex> lock(backends_mutex_);
    for (auto& backend : backends_) {
        if (backend.data_channel) {
            backend.data_channel->reset_sequence_tracking();
        }
    }
}

void ProxyBackendHandler::reset_data_channel_buffers() {
    std::lock_guard<std::mutex> lock(backends_mutex_);
    for (auto& backend : backends_) {
        if (backend.data_channel) {
            backend.data_channel->reset_buffers();
        }
    }
}

bool ProxyBackendHandler::reconnect_backend(BackendDevice& backend,
                                            std::chrono::milliseconds timeout) {
    if (log_mutex_) {
        std::lock_guard<std::mutex> lock(*log_mutex_);
        std::cerr << "[ProxyServer] Connection lost to "
                  << backend.host << ":" << backend.port
                  << ", reconnecting...\n";
    }
    try {
        if (!backend.control) return false;
        bool ok = backend.control->reconnect(
            std::chrono::milliseconds{500},
            std::make_optional(timeout));
        if (!ok) {
            if (log_mutex_) {
                std::lock_guard<std::mutex> lock(*log_mutex_);
                std::cerr << "[ProxyServer] Failed to reconnect to "
                          << backend.host << ":" << backend.port << "\n";
            }
            return false;
        }
        if (backend.data_channel) {
            backend.data_channel->reconnect();
        }

        // Re-extract the entity tree so cached_module reflects
        // post-reboot firmware (version, entity structure, etc.).
        pb::Module module = backend.control->extract(
            /*entity_path=*/"", /*recursive=*/true, /*specification=*/true,
            /*configuration=*/false, /*calibration=*/false,
            BACKEND_REQUEST_TIMEOUT_SECS);
        if (backend.location_stack.has_value() &&
            backend.location_carrier.has_value()) {
            for (auto& item : *module.mutable_items()) {
                if (item.has_entity_specification()) {
                    auto* loc = item.mutable_entity_specification()
                                    ->mutable_entity()
                                    ->mutable_location_v0();
                    loc->set_stack(backend.location_stack.value());
                    loc->set_carrier(backend.location_carrier.value());
                }
            }
        }
        backend.cached_module = std::move(module);

        if (log_mutex_) {
            std::lock_guard<std::mutex> lock(*log_mutex_);
            std::cerr << "[ProxyServer] Reconnected to "
                      << backend.host << ":" << backend.port << "\n";
        }
        return true;
    } catch (const std::exception& e) {
        if (log_mutex_) {
            std::lock_guard<std::mutex> lock(*log_mutex_);
            std::cerr << "[ProxyServer] Reconnect to "
                      << backend.host << ":" << backend.port
                      << " failed: " << e.what() << "\n";
        }
        return false;
    }
}

void ProxyBackendHandler::install_forward_callbacks() {
    // Read under active_session_mutex_ held by caller (set_active_session).
    std::weak_ptr<ClientSession> weak_session = active_session_;

    for (auto* backend_ptr : targets()) {
        auto& backend = *backend_ptr;

        auto forward_lambda = [this, weak_session, backend_ptr](pb::MessageV1& msg) {
            // Lock the weak reference. If the session has already been destroyed
            // (client disconnected before this callback fired), skip the send.
            auto sess = weak_session.lock();
            if (!sess) return;

            // Receiving data also counts as session activity; otherwise
            // waiting for TAKE_OFF across multiple mREDACs frequently
            // triggers session timeout.
            sess->last_activity = std::chrono::steady_clock::now();

            if (msg.has_run_state_change_message()) {
                // Stamp entity path so the client can identify which carrier
                // this state change originated from.
                if (!backend_ptr->carrier_paths.empty()) {
                    msg.mutable_run_state_change_message()
                        ->mutable_entity()
                        ->set_path("/" + backend_ptr->carrier_paths[0]);
                }
                pb::RunState new_state = msg.run_state_change_message().new_();
                std::string reason = msg.run_state_change_message().reason();
                if (!sess->send(msg)) {
                    if (log_mutex_) {
                        std::lock_guard<std::mutex> lk(*log_mutex_);
                        std::cerr << "[ProxyServer] WARNING: Failed to forward "
                                  << "RunStateChangeMessage to client\n";
                    }
                }

                if (new_state == pb::ERROR) {
                    std::string desc = "Backend device error from " +
                        backend_ptr->host + ":" + std::to_string(backend_ptr->port);
                    if (!backend_ptr->carrier_paths.empty()) {
                        desc += " (carrier " + backend_ptr->carrier_paths[0] + ")";
                    }
                    if (!reason.empty()) {
                        desc += " [Reason: " + reason + "]";
                    }
                    if (error_to_client_) {
                        error_to_client_(*sess, desc);
                    }
                    if (backend_ptr->data_channel) {
                        backend_ptr->data_channel->reset_buffers();
                    }
                    if (sess->transport()) {
                        sess->transport()->reset_buffers();
                    }
                    sess->done_received.store(true, std::memory_order_release);
                    return;
                }

                if (new_state == pb::DONE) {
                    if (backend_ptr->data_channel) {
                        auto udp_st = backend_ptr->data_channel->udp_stats();
                        if (udp_st && log_mutex_) {
                            std::lock_guard<std::mutex> lk(*log_mutex_);
                            std::cerr << "[ProxyServer] Backend "
                                      << backend_ptr->host << ":" << backend_ptr->port
                                      << " run stats: "
                                      << udp_st->packets_received << " packets received, "
                                      << udp_st->packets_dropped << " dropped, "
                                      << udp_st->bytes_received << " bytes received, "
                                      << udp_st->queue_size << " queued\n";
                        }
                        backend_ptr->data_channel->reset_udp_stats();
                        // Shrink any burst-grown transport buffers for this backend
                        // now that all samples have been forwarded.
                        backend_ptr->data_channel->reset_buffers();
                    }

                    if (run_coordinator_ && run_coordinator_->on_done()) {
                        sess->done_received.store(true, std::memory_order_release);

                        if (sess->transport()) {
                            auto tcp_st = sess->transport()->stats();
                            if (log_mutex_) {
                                std::lock_guard<std::mutex> lk(*log_mutex_);
                                std::cerr << "[ProxyServer] Client TCP stats: "
                                          << tcp_st.messages_sent << " messages sent, "
                                          << tcp_st.bytes_sent << " bytes sent, "
                                          << tcp_st.messages_received << " messages received, "
                                          << tcp_st.bytes_received << " bytes received\n";
                            }
                            sess->transport()->reset_stats();
                            sess->transport()->reset_buffers();
                        }
                    }
                    return;
                }

                if (new_state == pb::TAKE_OFF) {
                    if (run_coordinator_) {
                        run_coordinator_->on_take_off();
                    }
                }
                return;
            }

            if (debug_ && log_mutex_) {
                std::lock_guard<std::mutex> lk(*log_mutex_);
                std::cerr << "[ProxyServer] DEBUG: Forwarding data message to client "
                          << "(run_data=" << msg.has_run_data_message()
                          << ", run_data_end=" << msg.has_run_data_end_message()
                          << ")\n";
            }
            if (!sess->send(msg)) {
                if (log_mutex_) {
                    std::lock_guard<std::mutex> lk(*log_mutex_);
                    std::cerr << "[ProxyServer] WARNING: Failed to forward data message "
                              << "to client (run_data=" << msg.has_run_data_message()
                              << ", run_data_end=" << msg.has_run_data_end_message()
                              << ")\n";
                }
            }
        };

        if (backend.data_channel) {
            backend.data_channel->set_forward_callback(forward_lambda);
        }

        // In UDP mode the ControlChannel keeps the TCP recv loop running;
        // a backend that emits RunStateChangeMessage on TCP instead of UDP
        // would otherwise be dropped by dispatch_callback() with no handler
        // registered. Register the forward lambda so TCP-arriving state
        // changes reach the client the same way UDP-arriving ones do.
        if (backend.control) {
            backend.control->register_callback(
                pb::MessageV1::kRunStateChangeMessageFieldNumber,
                forward_lambda);
        }
    }
}

void ProxyBackendHandler::clear_forward_callbacks() {
    for (auto* backend : targets()) {
        if (backend->data_channel) {
            backend->data_channel->set_forward_callback(nullptr);
        }
        if (backend->control) {
            backend->control->unregister_callback(
                pb::MessageV1::kRunStateChangeMessageFieldNumber);
        }
    }
}

}  // namespace anabrid::pybrid::native

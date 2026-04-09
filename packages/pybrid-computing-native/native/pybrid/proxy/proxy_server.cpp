#include "pybrid/proxy/proxy_server.h"

#include <algorithm>
#include <chrono>
#include <condition_variable>
#include <cstdlib>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

#include "pybrid/proto/main.pb.h"
#include "pybrid/transport/tcp_transport.h"
#include "pybrid/utils/protobuf_helpers.h"
#include "pybrid/utils/uuid.h"

namespace anabrid::pybrid::native {

ClientSession::ClientSession(std::unique_ptr<TCPTransport> transport)
    : session_id_(utils::generate_uuid()),
      last_activity(std::chrono::steady_clock::now()),
      client_transport_(std::move(transport)) {
    if (!client_transport_) {
        throw std::invalid_argument("ClientSession: transport must not be null");
    }
}

ClientSession::~ClientSession() {
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
    return client_transport_->send(bytes.data(), bytes.size());
}

ProxyServer::ProxyServer(bool requires_auth)
    : requires_auth_(requires_auth) {
    if (requires_auth_) {
        const char* env = std::getenv("PYBRID_AUTHENTICATION");
        if (!env || std::string(env).empty()) {
            throw std::runtime_error(
                "PYBRID_AUTHENTICATION environment variable must be set "
                "when requires_auth is enabled");
        }
        auth_token_ = env;
    }
}

ProxyServer::~ProxyServer() {
    if (running_.load()) {
        stop();
    }
}

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
    return message.has_run_data_message() ||
           message.has_run_data_end_message() ||
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
        // First chunk for this carrier in this run — initialise.
        m_expected_chunk[carrier] = chunk + 1;
        return;
    }

    uint32_t expected = it->second;
    if (chunk != expected) {
        int64_t gap = static_cast<int64_t>(chunk) - static_cast<int64_t>(expected);
        if (m_log_mutex) {
            std::lock_guard<std::mutex> lock(*m_log_mutex);
            std::cerr << "[ProxyServer] WARNING: Sequence gap on carrier "
                      << carrier << ": expected chunk " << expected
                      << ", got " << chunk
                      << " (gap=" << gap << ")\n";
        } else {
            std::cerr << "[ProxyServer] WARNING: Sequence gap on carrier "
                      << carrier << ": expected chunk " << expected
                      << ", got " << chunk
                      << " (gap=" << gap << ")\n";
        }
    }
    it->second = chunk + 1;
}

void ProxyServer::add_backend(const std::string& host, uint16_t port,
                              std::optional<uint32_t> stack,
                              std::optional<uint32_t> carrier) {
    if (running_.load()) {
        throw std::logic_error("ProxyServer::add_backend(): must be called before start()");
    }

    if (!is_accepting_backends_) {
        throw std::logic_error("Backends have been finalized, no more changes are permitted.");
    }

    auto control = ControlChannel::create(host, port, BACKEND_CONNECT_TIMEOUT_SECS);
    control->start();

    pb::Module module = control->extract(
        /*entity_path=*/"", /*recursive=*/true, /*specification=*/true,
        /*configuration=*/false, /*calibration=*/false,
        BACKEND_REQUEST_TIMEOUT_SECS);

    // Extract entity info from specification items for routing.
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

                std::array<uint8_t, 4> ip{};
                std::stringstream ss{host};
                std::string segment;

                for (size_t i = 0; i < 4 && std::getline(ss, segment, '.'); ++i)
                    ip[i] = static_cast<uint8_t>(std::stoi(segment));

                pb::Address addr;
                addr.set_data(std::string(ip.begin(), ip.end()));
                map_backends_[entity.id()] = std::move(addr);
            }
        }
    }

    std::cerr << "[ProxyServer] Backend " << host << ":" << port
              << " — carrier: " << (carrier_paths.empty() ? "(none)" : carrier_paths[0]);
    if (stack.has_value() && carrier.has_value()) {
        std::cerr << " (stack " << stack.value() << ", carrier " << carrier.value() << ")";
    }
    std::cerr << "\n";

    control->reset(/*keep_calibration=*/true, /*sync=*/true, BACKEND_REQUEST_TIMEOUT_SECS);

    auto data_channel = std::make_unique<ForwardingDataChannel>();

    data_channel->set_log_mutex(&log_mutex_);

    if (debug_) {
        data_channel->set_debug(true);
    }

    // The proxy requires UDP for device→proxy data streaming (constant-rate).
    data_channel->set_control_channel(control.get());
    data_channel->set_require_udp(true);

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

void ProxyServer::map_backends()
{
    if (running_.load()) {
        throw std::logic_error("ProxyServer::map_backends(): must be called before start()");
    }

    pb::RegisterExternalEntitiesCommand cmd;
    for (auto& [k, v] : map_backends_)
        (*cmd.mutable_entities())[k] = v;

    std::vector<BackendDevice*> targets;
    for (auto& b : backends_) targets.push_back(&b);

    auto result = broadcast_to_backends(targets,
        [&cmd](BackendDevice&) {
            pb::MessageV1 req;
            req.set_id(utils::generate_uuid());
            *req.mutable_register_external_entities_command() = cmd;
            return req;
        });

    if (result.had_error) {
        throw std::runtime_error(
            "ProxyServer::map_backends(): " + result.error_text);
    }

    is_accepting_backends_ = false;
}

void ProxyServer::start(const std::string& host, uint16_t port) {
    bool expected = false;
    if (!running_.compare_exchange_strong(expected, true)) {
        return;
    }

    if (backends_.empty()) {
        running_.store(false);
        throw std::runtime_error("ProxyServer::start(): no backends have been added");
    }

    if (is_accepting_backends_) {
        running_.store(false);
        map_backends();
        running_.store(true);
    }

    server_.bind(port);
    server_.start();

    // RunDataMessage, RunDataEndMessage, and RunStateChangeMessage are handled
    // exclusively by ForwardingDataChannel (via UDP → handle_data_message() →
    // m_forward). The ControlChannel only handles ErrorMessage (TCP, infrequent).
    for (auto& backend : backends_) {
        ControlChannel* ctrl = backend.control.get();

        // Handle unsolicited ErrorMessage from a backend. Forwards to the active
        // client and notifies session_cv_ so the session handler can re-evaluate
        // state (e.g. backend disconnect). Acquires session_mutex_.
        ctrl->register_callback(
            pb::MessageV1::kErrorMessageFieldNumber,
            [this, ctrl](pb::MessageV1& msg) {
                if (!running_.load(std::memory_order_acquire)) return;
                if (debug_) {
                    std::cerr << "[ProxyServer] DEBUG: Error from device: "
                              << msg.error_message().description() << "\n";
                }
                std::lock_guard<std::mutex> lock(session_mutex_);
                ClientSession* active = active_session_;
                if (active && active->active.load()) {
                    if (!active->send(msg)) {
                        std::cerr << "[ProxyServer] WARNING: Failed to forward "
                                  << "ErrorMessage to client\n";
                    }
                }
                session_cv_.notify_one();
            });
    }

    // Build carrier-path → backend lookup map for O(1) routing.
    path_to_backend_.clear();
    for (auto& backend : backends_) {
        for (const auto& path : backend.carrier_paths) {
            path_to_backend_[path] = &backend;
        }
    }

    reconnect_thread_ = std::thread(&ProxyServer::reconnect_loop, this);
    accept_thread_ = std::thread(&ProxyServer::accept_loop, this);
}

void ProxyServer::stop() {
    bool expected = true;
    if (!running_.compare_exchange_strong(expected, false)) {
        return;
    }

    clear_forward_callbacks();
    {
        std::lock_guard<std::mutex> lock(session_mutex_);
        active_session_ = nullptr;
        active_session_id_.clear();
    }
    session_cv_.notify_all();

    // Stop order: cancel any in-flight reconnects → control channels →
    // init futures → data channels (unblocks pending operations before
    // teardown so reconnect loops yield promptly on shutdown).
    {
        std::lock_guard<std::mutex> lock(backends_mutex_);

        for (auto& backend : backends_) {
            if (backend.control) {
                backend.control->cancel_reconnect();
            }
        }
    }

    // Join the reconnect thread before tearing down channels — it may be
    // mid-reconnect and needs the control channels alive until it exits.
    if (reconnect_thread_.joinable()) reconnect_thread_.join();

    {
        std::lock_guard<std::mutex> lock(backends_mutex_);

        for (auto& backend : backends_) {
            if (backend.control) {
                backend.control->stop();
            }
        }

        for (auto& backend : backends_) {
            if (backend.data_channel_init_future.valid()) {
                backend.data_channel_init_future.wait_for(
                    std::chrono::duration<double>(
                        BACKEND_UDP_NEGOTIATION_TIMEOUT_SECS + 1.0));
            }
        }

        for (auto& backend : backends_) {
            if (backend.data_channel) {
                backend.data_channel->stop();
            }
        }
    }

    server_.stop();

    if (accept_thread_.joinable()) accept_thread_.join();

    {
        std::vector<std::thread> threads_to_join;
        {
            std::lock_guard<std::mutex> lock(session_mutex_);
            threads_to_join = std::move(session_threads_);
        }
        for (auto& t : threads_to_join) {
            if (t.joinable()) t.join();
        }
    }

    {
        std::lock_guard<std::mutex> lock(session_mutex_);
        while (!session_id_queue_.empty()) session_id_queue_.pop();
        session_map_.clear();
    }

    path_to_backend_.clear();
}

bool ProxyServer::is_running() const {
    return running_.load();
}

uint16_t ProxyServer::local_port() const {
    return server_.local_port();
}

void ProxyServer::set_session_timeout(double secs) {
    if (secs <= 0.0) {
        throw std::invalid_argument("ProxyServer::set_session_timeout(): timeout must be positive");
    }
    session_timeout_secs_ = secs;
}

void ProxyServer::set_max_sessions(size_t n) {
    if (n == 0) {
        throw std::invalid_argument("ProxyServer::set_max_sessions(): must be at least 1");
    }
    max_sessions_ = n;
}

void ProxyServer::set_debug(bool enabled) {
    debug_ = enabled;
}

void ProxyServer::set_backend_health(BackendDevice& backend,
                                     BackendHealth new_health) {
    {
        // Serialises store with notify_all() so waiters cannot miss the edge.
        std::lock_guard<std::mutex> lock(session_mutex_);
        backend.health.store(new_health, std::memory_order_release);
    }
    session_cv_.notify_all();
}

bool ProxyServer::all_backends_healthy() const {
    for (auto const& backend : backends_) {
        if (backend.health.load(std::memory_order_acquire) !=
            BackendHealth::HEALTHY) {
            return false;
        }
    }
    return true;
}

bool ProxyServer::reconnect_backend(BackendDevice& backend,
                                    std::chrono::milliseconds timeout) {
    {
        std::lock_guard<std::mutex> lock(log_mutex_);
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
            std::lock_guard<std::mutex> lock(log_mutex_);
            std::cerr << "[ProxyServer] Failed to reconnect to "
                      << backend.host << ":" << backend.port << "\n";
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

        {
            std::lock_guard<std::mutex> lock(log_mutex_);
            std::cerr << "[ProxyServer] Reconnected to "
                      << backend.host << ":" << backend.port << "\n";
        }
        return true;
    } catch (const std::exception& e) {
        std::lock_guard<std::mutex> lock(log_mutex_);
        std::cerr << "[ProxyServer] Reconnect to "
                  << backend.host << ":" << backend.port
                  << " failed: " << e.what() << "\n";
        return false;
    }
}

void ProxyServer::set_backend_health_for_test(size_t index, int new_health) {
    if (index >= backends_.size()) {
        throw std::out_of_range("backend index out of range");
    }
    set_backend_health(backends_[index],
                       static_cast<BackendHealth>(new_health));
}

int ProxyServer::get_backend_health(size_t index) const {
    if (index >= backends_.size()) {
        throw std::out_of_range("backend index out of range");
    }
    return static_cast<int>(
        backends_[index].health.load(std::memory_order_acquire));
}

void ProxyServer::reconnect_loop() {
    while (running_.load(std::memory_order_acquire)) {
        // Interruptible sleep: poll running_ in short intervals.
        for (int i = 0; i < 5 && running_.load(std::memory_order_acquire); ++i) {
            std::this_thread::sleep_for(RECONNECT_POLL_INTERVAL / 5);
        }
        if (!running_.load(std::memory_order_acquire)) break;

        for (auto& backend : backends_) {
            if (!running_.load(std::memory_order_acquire)) break;
            if (backend.health.load(std::memory_order_acquire) != BackendHealth::DEAD)
                continue;

            bool ok = reconnect_backend(backend, RECONNECT_ATTEMPT_TIMEOUT);
            if (ok) {
                set_backend_health(backend, BackendHealth::HEALTHY);
            }
        }
    }
}

void ProxyServer::accept_loop() {
    while (running_.load()) {
        AcceptedSocket sock = server_.accept(ACCEPT_POLL_TIMEOUT_SECS);
        if (!sock.is_valid()) {
            continue;
        }

        // Re-check running_ after accept() returns to avoid spawning sessions
        // during shutdown.
        if (!running_.load()) break;

        std::string peer_addr = sock.remote_host + ":" + std::to_string(sock.remote_port);

        auto transport = TCPTransport::from_accepted(sock);
        if (!transport) continue;
        transport->start();

        size_t current = active_session_count_.load(std::memory_order_acquire);
        if (current >= max_sessions_) {
            if (debug_) {
                std::cerr << "[ProxyServer] DEBUG: Client " << peer_addr
                          << " rejected (server overloaded, " << current
                          << "/" << max_sessions_ << " sessions)\n";
            }
            auto reject_session = std::make_unique<ClientSession>(std::move(transport));
            pb::MessageV1 error_msg;
            error_msg.mutable_error_message()->set_description("Server overloaded");
            reject_session->send(error_msg);
            continue;
        }

        active_session_count_.fetch_add(1, std::memory_order_acq_rel);

        auto session = std::make_shared<ClientSession>(std::move(transport));
        session->peer_address_ = peer_addr;

        if (debug_) {
            std::cerr << "[ProxyServer] DEBUG: Client connected from " << peer_addr
                      << " (session " << session->session_id_ << ")\n";
        }

        std::lock_guard<std::mutex> lock(session_mutex_);
        session_map_[session->session_id_] = session.get();
        session_threads_.emplace_back([this, session]() {
            run_session(*session);
            // Guard against unsigned underflow from a bug causing more decrements
            // than increments, which would permanently block new connections.
            size_t prev = active_session_count_.load(std::memory_order_acquire);
            if (prev == 0) {
                std::cerr << "[ProxyServer] BUG: active_session_count_ underflow "
                             "detected — skipping decrement\n";
            } else {
                active_session_count_.fetch_sub(1, std::memory_order_acq_rel);
            }
        });
    }
}

void ProxyServer::run_session(ClientSession& session) {
    if (!session.is_connected()) {
        return;
    }

    {
        std::unique_lock<std::mutex> lock(session_mutex_);
        register_session(session.session_id_, lock);
    }

    std::vector<uint8_t> buf(RECV_BUFFER_SIZE);
    bool became_active = false;

    while (running_.load() && session.is_connected()) {
        {
            std::lock_guard<std::mutex> lock(session_mutex_);
            if (active_session_id_ == session.session_id_) {
                active_session_ = &session;
                session.active.store(true, std::memory_order_release);
                became_active = true;
                // Raw pointer remains valid until clear_forward_callbacks() in deregister/stop.
                install_forward_callbacks(session);
                if (debug_) {
                    std::cerr << "[ProxyServer] DEBUG: Session " << session.session_id_
                              << " (" << session.peer_address_ << ") made active\n";
                }
                break;
            }
        }

        RecvResult result = session.transport()->recv(
            buf.data(), buf.size(), RECV_TIMEOUT_SECS);
        if (result.status == RecvStatus::Disconnected) break;
        if (result.status != RecvStatus::Success || result.bytes == 0) continue;

        pb::Envelope env;
        if (!env.ParseFromArray(buf.data(), static_cast<int>(result.bytes))) continue;
        if (!env.has_message_v1()) continue;
        pb::MessageV1 msg = env.message_v1();

        int kind = utils::get_kind_field_number(msg);
        if (kind == pb::MessageV1::kExtractCommandFieldNumber) {
            handle_extract(session, msg);
        } else if (kind == pb::MessageV1::kAuthRequestFieldNumber) {
            handle_auth(session, msg);
        } else if (kind == pb::MessageV1::kPingCommandFieldNumber) {
            pb::MessageV1 busy;
            busy.set_id(msg.id());
            busy.mutable_busy_response();
            session.send(busy);
        } else if (requires_auth_ && !session.authenticated_) {
            send_error_to_client(session, msg.id(), "Authentication required");
        } else {
            pb::MessageV1 busy;
            busy.set_id(msg.id());
            busy.mutable_busy_response();
            session.send(busy);
        }
    }

    // Sessions are never hot-swapped — once active, a session stays active until
    // it ends. No per-iteration active-status check is needed.
    session.transport()->reset_stats();

    while (became_active && running_.load() && session.is_connected()) {
        if (session.done_received.load(std::memory_order_acquire)) {
            std::chrono::steady_clock::time_point last;
            {
                std::lock_guard<std::mutex> lock(session_mutex_);
                last = session.last_activity;
            }
            double elapsed = std::chrono::duration<double>(
                std::chrono::steady_clock::now() - last).count();
            if (elapsed >= session_timeout_secs_) break;
        }

        // backends_ is read-only after start(); health is atomic.
        bool backend_lost = false;
        for (auto& backend : backends_) {
            auto h = backend.health.load(std::memory_order_acquire);
            if (h == BackendHealth::REBOOTING) {
                // Tolerated: handle_update owns this transition and will
                // flip the backend back to HEALTHY (or DEAD) once the
                // device is up again. The watchdog stays silent this tick.
                continue;
            }
            if (h == BackendHealth::DEAD) {
                {
                    std::lock_guard<std::mutex> lk(log_mutex_);
                    std::cerr << "[ProxyServer] Backend " << backend.host
                              << ":" << backend.port
                              << " is DEAD during session "
                              << session.session_id_ << "\n";
                }
                send_error_to_client(session, "",
                    "Cluster degraded: backend " + backend.host + ":" +
                    std::to_string(backend.port) + " is dead");
                backend_lost = true;
                break;
            }
            // HEALTHY: an unplanned TCP drop demotes the backend to DEAD so
            // subsequent ticks (and activate_next_session) see the state.
            if (backend.control && !backend.control->is_connected()) {
                {
                    std::lock_guard<std::mutex> lk(log_mutex_);
                    std::cerr << "[ProxyServer] Backend " << backend.host
                              << ":" << backend.port
                              << " disconnected during session "
                              << session.session_id_ << "\n";
                }
                set_backend_health(backend, BackendHealth::DEAD);
                send_error_to_client(session, "",
                    "Backend device disconnected: " + backend.host + ":" +
                    std::to_string(backend.port));
                backend_lost = true;
                break;
            }
        }
        if (backend_lost) break;

        RecvResult result = session.transport()->recv(
            buf.data(), buf.size(), RECV_TIMEOUT_SECS);
        if (result.status == RecvStatus::Disconnected) break;
        if (result.status != RecvStatus::Success || result.bytes == 0) continue;

        pb::Envelope env;
        if (!env.ParseFromArray(buf.data(), static_cast<int>(result.bytes))) continue;
        if (!env.has_message_v1()) continue;
        pb::MessageV1 msg = env.message_v1();

        {
            std::lock_guard<std::mutex> lock(session_mutex_);
            session.last_activity = std::chrono::steady_clock::now();
        }

        dispatch_message(session, msg);
    }

    if (debug_) {
        std::cerr << "[ProxyServer] DEBUG: Session " << session.session_id_
                  << " (" << session.peer_address_ << ") ended\n";
    }

    if (session.is_connected()) {
        session.transport()->drain(DRAIN_TIMEOUT_SECS);
    }

    {
        std::unique_lock<std::mutex> lock(session_mutex_);
        deregister_session(session.session_id_, lock);
        session_map_.erase(session.session_id_);
    }
    session_cv_.notify_all();
}

void ProxyServer::register_session(const std::string& id,
                                    std::unique_lock<std::mutex>& lock) {
    session_id_queue_.push(id);
    if (active_session_id_.empty()) {
        // No session currently active — route promotion through
        // activate_next_session() so the lazy-recovery path runs if any
        // backend is DEAD.
        activate_next_session(lock);
    }
}

void ProxyServer::deregister_session(const std::string& id,
                                     std::unique_lock<std::mutex>& lock) {
    bool was_active = (active_session_id_ == id);

    // Rebuild the queue without this session's ID.
    std::queue<std::string> new_queue;
    while (!session_id_queue_.empty()) {
        std::string front = session_id_queue_.front();
        session_id_queue_.pop();
        if (front != id) {
            new_queue.push(front);
        }
    }
    session_id_queue_ = std::move(new_queue);

    if (was_active) {
        active_session_ = nullptr;
        clear_forward_callbacks();
        active_session_id_.clear();
        activate_next_session(lock);
    }
}

void ProxyServer::activate_next_session(std::unique_lock<std::mutex>& lock) {
    if (session_id_queue_.empty()) {
        active_session_id_.clear();
        active_session_ = nullptr;
        return;
    }

    // Wait until all backends are healthy. The background reconnect_loop
    // handles DEAD backends; handle_update handles REBOOTING ones. Both
    // notify session_cv_ on health transitions.
    session_cv_.wait(lock, [this]() {
        return all_backends_healthy()
            || !running_.load(std::memory_order_acquire)
            || session_id_queue_.empty();
    });

    if (!running_.load(std::memory_order_acquire) ||
        session_id_queue_.empty()) {
        active_session_id_.clear();
        active_session_ = nullptr;
        return;
    }

    active_session_id_ = session_id_queue_.front();
    auto it = session_map_.find(active_session_id_);
    if (it != session_map_.end()) {
        active_session_ = it->second;
        it->second->active.store(true, std::memory_order_release);
        if (debug_) {
            std::cerr << "[ProxyServer] DEBUG: Session " << active_session_id_
                      << " (" << it->second->peer_address_
                      << ") made active\n";
        }
    } else {
        active_session_ = nullptr;
    }
    session_cv_.notify_all();
}

void ProxyServer::install_forward_callbacks(ClientSession& session) {
    // The session pointer is guaranteed alive until clear_forward_callbacks() is
    // called (in deregister_session and stop), so using a raw pointer here is safe.
    ClientSession* sess = &session;

    for (auto& backend : backends_) {
        if (!backend.data_channel) continue;

        BackendDevice* backend_ptr = &backend;

        backend.data_channel->set_forward_callback(
            [this, sess, backend_ptr](pb::MessageV1& msg) {

                // Receiving data also counts as session activity; otherwise
                // waiting for TAKE_OFF across multiple mREDACs frequently
                // triggers session timeout.
                {
                    std::lock_guard<std::mutex> lock(session_mutex_);
                    sess->last_activity = std::chrono::steady_clock::now();
                }

                if (msg.has_run_state_change_message()) {
                    // Stamp entity path so the client can identify which carrier
                    // this state change originated from.
                    if (!backend_ptr->carrier_paths.empty()) {
                        msg.mutable_run_state_change_message()
                            ->mutable_entity()
                            ->set_path("/" + backend_ptr->carrier_paths[0]);
                    }
                    pb::RunState new_state = msg.run_state_change_message().new_();
                    if (!sess->send(msg)) {
                        std::lock_guard<std::mutex> lk(log_mutex_);
                        std::cerr << "[ProxyServer] WARNING: Failed to forward "
                                  << "RunStateChangeMessage to client\n";
                    }
                    on_forwarded_run_state(*sess, *backend_ptr, new_state, 
                        msg.run_state_change_message().reason());
                    session_cv_.notify_one();
                    return;
                }

                if (debug_) {
                    std::lock_guard<std::mutex> lk(log_mutex_);
                    std::cerr << "[ProxyServer] DEBUG: Forwarding data message to client "
                              << "(run_data=" << msg.has_run_data_message()
                              << ", run_data_end=" << msg.has_run_data_end_message()
                              << ")\n";
                }
                if (!sess->send(msg)) {
                    std::lock_guard<std::mutex> lk(log_mutex_);
                    std::cerr << "[ProxyServer] WARNING: Failed to forward data message "
                              << "to client (run_data=" << msg.has_run_data_message()
                              << ", run_data_end=" << msg.has_run_data_end_message()
                              << ")\n";
                }
            });
    }
}

void ProxyServer::clear_forward_callbacks() {
    for (auto& backend : backends_) {
        if (backend.data_channel) {
            backend.data_channel->set_forward_callback(nullptr);
        }
    }
}

void ProxyServer::on_forwarded_run_state(
    ClientSession& session, BackendDevice& backend, pb::RunState state, const std::string reason) {
    bool is_done = (state == pb::DONE);
    bool is_take_off = (state == pb::TAKE_OFF);
    bool is_error = (state == pb::ERROR);

    if (is_error) {
        std::string desc = "Backend device error from " +
            backend.host + ":" + std::to_string(backend.port);
        if (!backend.carrier_paths.empty()) {
            desc += " (carrier " + backend.carrier_paths[0] + ")";
        }
        if(reason.size() > 0)
            desc += " [Reason: " + reason + "]";
        send_error_to_client(session, "", desc);
        session.done_received.store(true, std::memory_order_release);
        return;
    }

    if (is_done) {
        if (backend.data_channel) {
            auto udp_st = backend.data_channel->udp_stats();
            if (udp_st) {
                std::lock_guard<std::mutex> lk(log_mutex_);
                std::cerr << "[ProxyServer] Backend "
                          << backend.host << ":" << backend.port
                          << " run stats: "
                          << udp_st->packets_received << " packets received, "
                          << udp_st->packets_dropped << " dropped, "
                          << udp_st->bytes_received << " bytes received, "
                          << udp_st->queue_size << " queued\n";
            }
            backend.data_channel->reset_udp_stats();
        }

        // Only mark session as DONE once ALL backends have reported DONE,
        // mirroring the TAKE_OFF barrier logic.
        size_t dcount = done_count_.fetch_add(1, std::memory_order_acq_rel) + 1;
        if (dcount >= backends_.size()) {
            session.done_received.store(true, std::memory_order_release);

            if (session.transport()) {
                auto tcp_st = session.transport()->stats();
                std::lock_guard<std::mutex> lk(log_mutex_);
                std::cerr << "[ProxyServer] Client TCP stats: "
                          << tcp_st.messages_sent << " messages sent, "
                          << tcp_st.bytes_sent << " bytes sent, "
                          << tcp_st.messages_received << " messages received, "
                          << tcp_st.bytes_received << " bytes received\n";
                session.transport()->reset_stats();
            }
        }
    }

    if (is_take_off) {
        uint64_t gen = run_id_.load(std::memory_order_acquire);
        size_t count = take_off_count_.fetch_add(1, std::memory_order_acq_rel) + 1;
        
        // this used to be the entrypoint for USB-SPI-based synchronization
    }
}

void ProxyServer::dispatch_message(ClientSession& session, const pb::MessageV1& msg) {
    int kind = utils::get_kind_field_number(msg);

    if (requires_auth_ && !session.authenticated_ &&
        kind != pb::MessageV1::kAuthRequestFieldNumber) {
        send_error_to_client(session, msg.id(), "Authentication required");
        return;
    }

    switch (kind) {
        case pb::MessageV1::kResetCommandFieldNumber:
            handle_reset(session, msg);
            break;
        case pb::MessageV1::kExtractCommandFieldNumber:
            handle_extract(session, msg);
            break;
        case pb::MessageV1::kConfigCommandFieldNumber:
            handle_config(session, msg);
            break;
        case pb::MessageV1::kStartRunCommandFieldNumber:
            handle_start_run(session, msg);
            break;
        case pb::MessageV1::kAuthRequestFieldNumber:
            handle_auth(session, msg);
            break;
        case pb::MessageV1::kCalibrationCommandFieldNumber:
            handle_calibrate(session, msg);
            break;
        case pb::MessageV1::kUdpDataStreamingCommandFieldNumber:
            handle_udp_streaming(session, msg);
            break;
        case pb::MessageV1::kRegisterExternalEntitiesCommandFieldNumber:
            handle_register_external_entities(session, msg);
            break;
        case pb::MessageV1::kUpdateCommandFieldNumber:
            handle_update(session, msg);
            break;
        case pb::MessageV1::kPingCommandFieldNumber: {
            pb::MessageV1 ping_response;
            ping_response.set_id(msg.id());
            ping_response.mutable_success_message();
            session.send(ping_response);
            break;
        }
        default:
            if(debug_)
            {
                std::cerr << "Unhandled message type received: " <<
                    kind << ", ignoring..." << std::endl;
            }
            break;
    }
}

}  // namespace anabrid::pybrid::native

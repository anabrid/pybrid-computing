#include "pybrid/proxy/proxy_server.h"

#include <algorithm>
#include <chrono>
#include <cstdlib>
#include <iostream>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

#include "pybrid/proto/main.pb.h"
#include "pybrid/transport/tcp_transport.h"
#include "pybrid/transport/udp_socket.h"
#include "pybrid/utils/protobuf_helpers.h"
#include "pybrid/utils/uuid.h"

namespace anabrid::pybrid::native {

ProxyServer::ProxyServer(bool requires_auth) : backend_handler_(&log_mutex_), requires_auth_(requires_auth) {
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

void ProxyServer::add_backend(
    const std::string& host, uint16_t port, std::optional<uint32_t> stack, std::optional<uint32_t> carrier) {
    if (running_.load()) {
        throw std::logic_error("ProxyServer::add_backend(): must be called before start()");
    }

    backend_handler_.add_backend(host, port, stack, carrier);
}

void ProxyServer::start(const std::string& host, uint16_t port) {
    bool expected = false;
    if (!running_.compare_exchange_strong(expected, true)) {
        return;
    }

    if (backend_handler_.empty()) {
        running_.store(false);
        throw std::runtime_error("ProxyServer::start(): no backends have been added");
    }

    server_.bind(port);
    server_.start();

    run_coordinator_.configure(backend_handler_.size());

    // Order matters: backend_handler_.start() builds path_to_backend_ and
    // pins the backend topology; the reconnect loop iterates that topology.
    // Spawn the reconnect thread only AFTER the handler reports started.
    backend_handler_.start(run_coordinator_, [this](ClientSession& sess, const std::string& desc) {
        send_error_to_client(sess, "", desc);
    });

    reconnect_thread_ = std::thread(&ProxyServer::reconnect_loop, this);
    server_thread_ = std::thread(&ProxyServer::server_loop, this);
    session_thread_ = std::thread(&ProxyServer::session_loop, this);
}

void ProxyServer::stop() {
    bool expected = true;
    if (!running_.compare_exchange_strong(expected, false)) {
        return;
    }

    // Join the session/server threads BEFORE backend_handler_.stop():
    // a session-loop iteration in flight may call set_active_session, and
    // the handler must still be alive while that runs.
    if (server_thread_.joinable()) server_thread_.join();
    if (session_thread_.joinable()) session_thread_.join();

    // Join the reconnect thread BEFORE backend_handler_.stop(): the loop calls
    // backend_handler_.reconnect_backend(), which races with handler teardown.
    if (reconnect_thread_.joinable()) reconnect_thread_.join();

    backend_handler_.stop();

    server_.stop();

    {
        std::lock_guard<std::mutex> lock(deque_mutex_);
        active_.reset();
        active_weak_.reset();
        session_deque_.clear();
    }
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
    backend_handler_.set_debug(enabled);
}

bool ProxyServer::all_backends_healthy() const {
    return backend_handler_.all_backends_healthy();
}

void ProxyServer::set_backend_health_for_test(size_t index, int new_health) {
    backend_handler_.set_backend_health_for_test(index, new_health);
}

int ProxyServer::get_backend_health(size_t index) const {
    return backend_handler_.get_backend_health(index);
}

// One-shot peek for ping immediately after accept. If the first message on
// the wire is a ping, send pong and return true (the caller drops the
// transport). If it is anything else, move it into out_pending so it can
// be carried into the queued session and processed by poll_queued().
bool ProxyServer::peek_for_ping(
    TCPTransport& transport, double timeout_secs, std::optional<pb::MessageV1>& out_pending) {
    out_pending.reset();
    std::vector<uint8_t> buf(RECV_BUFFER_SIZE);
    RecvResult result = transport.recv(buf.data(), buf.size(), timeout_secs);
    if (result.status != RecvStatus::Success || result.bytes == 0) {
        return false;
    }

    pb::Envelope env;
    if (!env.ParseFromArray(buf.data(), static_cast<int>(result.bytes))) {
        return false;
    }

    if (env.has_generic() && env.generic().has_ping_command()) {
        pb::Envelope reply;
        reply.mutable_generic()->mutable_ping_response();
        std::string bytes;
        if (reply.SerializeToString(&bytes)) {
            try {
                transport.send(bytes.data(), bytes.size());
            } catch (const std::runtime_error&) {
                // Client disconnected mid-pong; nothing to do.
            }
        }
        return true;
    }

    if (env.has_message_v1()) {
        out_pending = env.message_v1();
    }
    return false;
}

void ProxyServer::server_loop() {
    while (running_.load()) {
        AcceptedSocket sock = server_.accept(ACCEPT_POLL_TIMEOUT_SECS);
        if (sock.is_valid() && running_.load()) {
            std::string peer_addr = sock.remote_host + ":" + std::to_string(sock.remote_port);

            auto transport = TCPTransport::from_accepted(std::move(sock));
            if (!transport) {
                poll_queued();
                continue;
            }
            transport->start();

            std::optional<pb::MessageV1> pending;
            if (peek_for_ping(*transport, PEEK_TIMEOUT_SECS, pending)) {
                // Ping handled inline; transport drops at scope exit.
                poll_queued();
                continue;
            }

            bool admit = false;
            {
                std::lock_guard<std::mutex> lock(deque_mutex_);
                size_t total = session_deque_.size() + (active_ ? 1 : 0);
                if (total < max_sessions_) {
                    auto session = std::make_shared<ClientSession>(std::move(transport), std::move(pending));
                    session->peer_address_ = peer_addr;
                    if (debug_) {
                        std::cerr << "[ProxyServer] DEBUG: Client connected from " << peer_addr << " (session "
                                  << session->session_id_ << ")\n";
                    }
                    session_deque_.push_back(std::move(session));
                    admit = true;
                }
            }

            if (!admit) {
                if (debug_) {
                    std::cerr << "[ProxyServer] DEBUG: Client " << peer_addr << " rejected (server overloaded)\n";
                }
                pb::MessageV1 error_msg;
                error_msg.mutable_error_message()->set_description("Server overloaded");
                std::string bytes = utils::serialize_message(error_msg);
                if (!bytes.empty() && transport && transport->is_connected()) {
                    try {
                        transport->send(bytes.data(), bytes.size());
                    } catch (const std::runtime_error&) {
                        // Client already gone.
                    }
                }
                // transport leaves scope here; ~TCPTransport closes the socket.
            }
        }

        poll_queued();
    }
}

void ProxyServer::poll_queued() {
    std::vector<std::shared_ptr<ClientSession>> snapshot;
    {
        std::lock_guard<std::mutex> lock(deque_mutex_);
        snapshot.assign(session_deque_.begin(), session_deque_.end());
    }
    if (snapshot.empty()) return;

    std::vector<std::shared_ptr<ClientSession>> to_drop;
    std::vector<uint8_t> buf(RECV_BUFFER_SIZE);

    for (auto& s : snapshot) {
        if (!s->is_connected()) {
            to_drop.push_back(s);
            continue;
        }

        std::optional<pb::MessageV1> msg = s->take_pending_first_message();
        if (!msg.has_value()) {
            RecvResult result = s->transport()->recv(buf.data(), buf.size(), PRE_ADMIT_RECV_TIMEOUT_SECS);
            if (result.status == RecvStatus::Disconnected) {
                to_drop.push_back(s);
                continue;
            }
            if (result.status != RecvStatus::Success || result.bytes == 0) {
                continue;
            }

            pb::Envelope env;
            if (!env.ParseFromArray(buf.data(), static_cast<int>(result.bytes))) {
                continue;
            }

            if (env.has_generic() && env.generic().has_ping_command()) {
                handle_ping(*s);
                continue;
            }

            if (!env.has_message_v1()) continue;
            msg = env.message_v1();
        }

        int kind = utils::get_kind_field_number(*msg);

        // Defer non-auth messages while any backend is unhealthy so the
        // session goes through the worker's promotion gate, where backend
        // recovery is awaited. Auth is safe to handle independently of
        // backend state.
        if (kind != pb::MessageV1::kAuthRequestFieldNumber && !all_backends_healthy()) {
            s->stash_first_message(std::move(*msg));
            continue;
        }

        if (kind == pb::MessageV1::kAuthRequestFieldNumber) {
            handle_auth(*s, *msg);
        } else if (requires_auth_ && !s->authenticated_) {
            send_error_to_client(*s, msg->id(), "Authentication required");
        } else if (kind == pb::MessageV1::kExtractCommandFieldNumber) {
            handle_extract(*s, *msg);
        } else {
            pb::MessageV1 busy;
            busy.set_id(msg->id());
            busy.mutable_busy_response();
            s->send(busy);
        }
    }

    if (!to_drop.empty()) {
        std::lock_guard<std::mutex> lock(deque_mutex_);
        for (auto& sp : to_drop) {
            auto it = std::find(session_deque_.begin(), session_deque_.end(), sp);
            if (it != session_deque_.end()) {
                session_deque_.erase(it);
            }
        }
    }
}

void ProxyServer::session_loop() {
    while (running_.load()) {
        std::shared_ptr<ClientSession> sess;
        {
            std::lock_guard<std::mutex> lock(deque_mutex_);
            // Drop disconnected fronts (clients gave up while we slept).
            while (!session_deque_.empty() && !session_deque_.front()->is_connected()) {
                session_deque_.pop_front();
            }
            if (!session_deque_.empty() && all_backends_healthy()) {
                active_ = session_deque_.front();
                session_deque_.pop_front();
                active_weak_ = active_;
                sess = active_;
            }
        }

        if (!sess) {
            std::this_thread::sleep_for(WORKER_POLL_INTERVAL);
            continue;
        }

        std::weak_ptr<ClientSession> weak_sess = sess;
        backend_handler_.set_active_session(weak_sess);
        sess->active.store(true, std::memory_order_release);
        sess->last_activity = std::chrono::steady_clock::now();

        if (debug_) {
            std::lock_guard<std::mutex> lk(log_mutex_);
            std::cerr << "[ProxyServer] DEBUG: Session " << sess->session_id_ << " (" << sess->peer_address_
                      << ") made active\n";
        }

        try {
            run_active_dispatch(*sess);
        } catch (const std::exception& e) {
            std::lock_guard<std::mutex> lk(log_mutex_);
            std::cerr << "[ProxyServer] Session " << sess->session_id_ << " ended with error: " << e.what() << "\n";
        } catch (...) {
            std::lock_guard<std::mutex> lk(log_mutex_);
            std::cerr << "[ProxyServer] Session " << sess->session_id_ << " ended with unknown error\n";
        }

        if (debug_) {
            std::lock_guard<std::mutex> lk(log_mutex_);
            std::cerr << "[ProxyServer] DEBUG: Session " << sess->session_id_ << " (" << sess->peer_address_
                      << ") ended\n";
        }

        if (sess->is_connected()) {
            sess->transport()->drain(DRAIN_TIMEOUT_SECS);
        }

        backend_handler_.set_active_session({});

        // Shrink any per-session buffers held by backends so the next
        // session does not inherit growth from this one's bursts.
        for (auto* backend : backend_handler_.targets()) {
            if (backend->data_channel) {
                backend->data_channel->reset_buffers();
            }
        }

        sess.reset();
        {
            std::lock_guard<std::mutex> lock(deque_mutex_);
            active_.reset();
            active_weak_.reset();
        }
    }
}

void ProxyServer::run_active_dispatch(ClientSession& session) {
    std::vector<uint8_t> buf(RECV_BUFFER_SIZE);
    session.transport()->reset_stats();

    if (auto pending = session.take_pending_first_message()) {
        session.last_activity = std::chrono::steady_clock::now();
        dispatch_message(session, *pending);
    }

    while (running_.load() && session.is_connected()) {
        if (session.done_received.load(std::memory_order_acquire)) {
            auto last = session.last_activity;
            double elapsed = std::chrono::duration<double>(std::chrono::steady_clock::now() - last).count();
            if (elapsed >= session_timeout_secs_) break;
        }

        // The backend list is immutable after start(); health is atomic.
        // Scan ALL backends before breaking so every disconnected device
        // is demoted to DEAD in one pass — the reconnect_loop then picks
        // them all up in parallel instead of one per session attempt.
        bool backend_lost = false;
        for (auto* backend : backend_handler_.targets()) {
            auto h = backend->health.load(std::memory_order_acquire);
            if (h == BackendHealth::REBOOTING) {
                continue;
            }
            if (h == BackendHealth::DEAD) {
                backend_lost = true;
                continue;
            }
            if (backend->control && !backend->control->is_connected()) {
                {
                    std::lock_guard<std::mutex> lk(log_mutex_);
                    std::cerr << "[ProxyServer] Backend " << backend->host << ":" << backend->port
                              << " disconnected during session " << session.session_id_ << "\n";
                }
                backend_handler_.set_backend_health(*backend, BackendHealth::DEAD);
                backend_lost = true;
            }
        }
        if (backend_lost) {
            send_error_to_client(session, "", "Cluster degraded: one or more backends disconnected");
            break;
        }

        RecvResult result = session.transport()->recv(buf.data(), buf.size(), RECV_TIMEOUT_SECS);
        if (result.status == RecvStatus::Disconnected) break;
        if (result.status != RecvStatus::Success || result.bytes == 0) continue;

        pb::Envelope env;
        if (!env.ParseFromArray(buf.data(), static_cast<int>(result.bytes))) continue;

        if (env.has_generic() && env.generic().has_ping_command()) {
            handle_ping(session);
            continue;
        }

        if (!env.has_message_v1()) continue;
        pb::MessageV1 msg = env.message_v1();

        session.last_activity = std::chrono::steady_clock::now();

        dispatch_message(session, msg);
    }
}

void ProxyServer::reconnect_loop() {
    while (running_.load(std::memory_order_acquire)) {
        // Interruptible sleep: poll running_ in short intervals.
        for (int i = 0; i < 5 && running_.load(std::memory_order_acquire); ++i) {
            std::this_thread::sleep_for(ProxyBackendHandler::RECONNECT_POLL_INTERVAL / 5);
        }
        if (!running_.load(std::memory_order_acquire)) break;

        std::weak_ptr<ClientSession> active_snapshot;
        {
            std::lock_guard<std::mutex> lock(deque_mutex_);
            active_snapshot = active_weak_;
        }
        bool session_active = active_snapshot.lock() != nullptr;

        for (auto* backend : backend_handler_.targets()) {
            if (!running_.load(std::memory_order_acquire)) break;

            auto h = backend->health.load(std::memory_order_acquire);
            if (h == BackendHealth::REBOOTING) continue;

            if (h == BackendHealth::HEALTHY) {
                if (!backend->control || !backend->control->is_connected()) {
                    // Already known-disconnected (passive detection).
                } else if (!session_active) {
                    // No session owns the control channels — safe to send
                    // an active probe via Envelope-level GenericMessage ping.
                    try {
                        backend->control->ping(ProxyBackendHandler::PING_PROBE_TIMEOUT_SECS);
                        continue;
                    } catch (...) {
                        // Ping failed — fall through to DEAD + reconnect.
                    }
                } else {
                    // Session active — rely on passive is_connected() only.
                    continue;
                }
                {
                    std::lock_guard<std::mutex> lock(log_mutex_);
                    std::cerr << "[ProxyServer] Backend " << backend->host << ":" << backend->port
                              << " failed liveness probe\n";
                }
                backend_handler_.set_backend_health(*backend, BackendHealth::DEAD);
            }

            bool ok = backend_handler_.reconnect_backend(*backend, ProxyBackendHandler::RECONNECT_ATTEMPT_TIMEOUT);
            if (ok) {
                backend_handler_.set_backend_health(*backend, BackendHealth::HEALTHY);
            }
        }
    }
}

void ProxyServer::dispatch_message(ClientSession& session, const pb::MessageV1& msg) {
    int kind = utils::get_kind_field_number(msg);

    if (requires_auth_ && !session.authenticated_ && kind != pb::MessageV1::kAuthRequestFieldNumber) {
        send_error_to_client(session, msg.id(), "Authentication required");
        return;
    }

    switch (kind) {
        case pb::MessageV1::kResetCommandFieldNumber: handle_reset(session, msg); break;
        case pb::MessageV1::kExtractCommandFieldNumber: handle_extract(session, msg); break;
        case pb::MessageV1::kConfigCommandFieldNumber: handle_config(session, msg); break;
        case pb::MessageV1::kStartRunCommandFieldNumber: handle_start_run(session, msg); break;
        case pb::MessageV1::kAuthRequestFieldNumber: handle_auth(session, msg); break;
        case pb::MessageV1::kCalibrationCommandFieldNumber: handle_calibrate(session, msg); break;
        case pb::MessageV1::kUdpDataStreamingCommandFieldNumber: handle_udp_streaming(session, msg); break;
        case pb::MessageV1::kUpdateCommandFieldNumber: handle_update(session, msg); break;
        case pb::MessageV1::kPingCommandFieldNumber: handle_ping(session); break;
        case pb::MessageV1::kGetOverloadStatusCommandFieldNumber: handle_get_overload_status(session, msg); break;
        default:
            if (debug_) {
                std::cerr << "Unhandled message type received: " << kind << ", ignoring..." << std::endl;
            }
            break;
    }
}

}  // namespace anabrid::pybrid::native

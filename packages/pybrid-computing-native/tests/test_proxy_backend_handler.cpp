// Copyright (c) 2022-2025 anabrid GmbH
// SPDX-License-Identifier: MIT OR GPL-2.0-or-later

#include <gtest/gtest.h>

#include <atomic>
#include <chrono>
#include <future>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <thread>
#include <vector>

#include "pybrid/channel/control_channel.h"
#include "pybrid/proto/main.pb.h"
#include "pybrid/proxy/proxy_backend_handler.h"
#include "pybrid/proxy/proxy_run_coordinator.h"
#include "pybrid/proxy/proxy_session.h"
#include "pybrid/transport/tcp_server.h"
#include "pybrid/transport/tcp_transport.h"

using namespace anabrid::pybrid::native;

namespace {

constexpr double TEST_TIMEOUT_SECS = 5.0;
constexpr size_t RECV_BUF_SIZE = 65536;

const std::string CARRIER_MAC_A = "aa-bb-cc-dd-ee-ff";
const std::string CARRIER_PATH_A = "/" + CARRIER_MAC_A;

const std::string CARRIER_MAC_B = "11-22-33-44-55-66";
const std::string CARRIER_PATH_B = "/" + CARRIER_MAC_B;

// Minimal mock backend kept inline so this test target is self-contained.
class MockBackend {
public:
    explicit MockBackend(const std::string& carrier_path = CARRIER_PATH_A) : carrier_path_(carrier_path) {
        server_.bind(0);
        server_.start();
    }

    ~MockBackend() {
        if (transport_) {
            transport_->stop();
        }
        server_.stop();
    }

    MockBackend(const MockBackend&) = delete;
    MockBackend& operator=(const MockBackend&) = delete;

    uint16_t port() const { return server_.local_port(); }
    const std::string& carrier_path() const { return carrier_path_; }

    void accept_connection(double timeout_secs = TEST_TIMEOUT_SECS) {
        AcceptedSocket sock = server_.accept(timeout_secs);
        if (!sock.is_valid()) {
            throw std::runtime_error("MockBackend: accept timed out");
        }
        transport_ = TCPTransport::from_accepted(std::move(sock));
        if (!transport_) {
            throw std::runtime_error("MockBackend: from_accepted returned null");
        }
        transport_->start();
    }

    pb::MessageV1 recv_message(double timeout_secs = TEST_TIMEOUT_SECS) {
        std::vector<uint8_t> buf(RECV_BUF_SIZE);
        RecvResult result = transport_->recv(buf.data(), buf.size(), timeout_secs);
        if (result.status != RecvStatus::Success || result.bytes == 0) {
            throw std::runtime_error("MockBackend::recv_message: no data");
        }
        pb::Envelope env;
        if (!env.ParseFromArray(buf.data(), static_cast<int>(result.bytes))) {
            throw std::runtime_error("MockBackend::recv_message: parse failed");
        }
        if (!env.has_message_v1()) {
            throw std::runtime_error("MockBackend::recv_message: no message_v1");
        }
        return env.message_v1();
    }

    void send_message(const pb::MessageV1& msg) {
        pb::Envelope env;
        *env.mutable_message_v1() = msg;
        std::string bytes;
        if (!env.SerializeToString(&bytes)) {
            throw std::runtime_error("MockBackend::send_message: serialize failed");
        }
        if (!transport_->send(bytes.data(), bytes.size())) {
            throw std::runtime_error("MockBackend::send_message: send failed");
        }
    }

    pb::MessageV1 make_extract_response(const std::string& request_id) const {
        pb::MessageV1 resp;
        resp.set_id(request_id);
        auto* mod = resp.mutable_extract_response()->mutable_module();
        auto* item = mod->add_items();
        pb::Entity* carrier = item->mutable_entity_specification()->mutable_entity();
        carrier->set_id(carrier_path_);
        carrier->set_class_(pb::Entity::CARRIER);
        return resp;
    }

    pb::MessageV1 make_reset_response(const std::string& request_id) const {
        pb::MessageV1 resp;
        resp.set_id(request_id);
        resp.mutable_reset_response()->mutable_entity()->set_path(carrier_path_);
        return resp;
    }

    pb::MessageV1 make_success_response(const std::string& request_id) const {
        pb::MessageV1 resp;
        resp.set_id(request_id);
        resp.mutable_success_message();
        return resp;
    }

    pb::MessageV1 make_udp_refused_response(const std::string& request_id) const {
        pb::MessageV1 resp;
        resp.set_id(request_id);
        resp.mutable_udp_data_streaming_refused_response()->set_reason("UDP not supported in tests");
        return resp;
    }

    pb::MessageV1 make_run_state_notification(pb::RunState new_state) const {
        pb::MessageV1 notif;
        notif.mutable_run_state_change_message()->set_new_(new_state);
        return notif;
    }

    // Drain ExtractCommand + ResetCommand + UdpDataStreamingCommand and reply
    // to each. UDP is refused so the data channel falls back to TCP fallback;
    // RunStateChangeMessage notifications sent over the TCP socket exercise
    // the TCP-arriving forward path inside ProxyBackendHandler.
    void serve_add_backend_handshake_tcp_fallback() {
        pb::MessageV1 extract_req = recv_message();
        if (!extract_req.has_extract_command()) {
            throw std::runtime_error("MockBackend: expected ExtractCommand");
        }
        send_message(make_extract_response(extract_req.id()));

        pb::MessageV1 reset_req = recv_message();
        if (!reset_req.has_reset_command()) {
            throw std::runtime_error("MockBackend: expected ResetCommand");
        }
        send_message(make_reset_response(reset_req.id()));

        pb::MessageV1 udp_req = recv_message();
        if (!udp_req.has_udp_data_streaming_command()) {
            throw std::runtime_error("MockBackend: expected UdpDataStreamingCommand");
        }
        send_message(make_udp_refused_response(udp_req.id()));
    }

    // After a reconnect, ProxyBackendHandler::reconnect_backend first runs
    // DataChannel::reconnect() (which re-negotiates UDP) and then re-extracts
    // through the control channel.
    void serve_reconnect_handshake_tcp_fallback() {
        pb::MessageV1 udp_req = recv_message();
        if (!udp_req.has_udp_data_streaming_command()) {
            throw std::runtime_error("MockBackend: expected UdpDataStreamingCommand on reconnect");
        }
        send_message(make_udp_refused_response(udp_req.id()));

        pb::MessageV1 extract_req = recv_message();
        if (!extract_req.has_extract_command()) {
            throw std::runtime_error("MockBackend: expected ExtractCommand on reconnect");
        }
        send_message(make_extract_response(extract_req.id()));
    }

    void disconnect() {
        if (transport_) {
            transport_->stop();
            transport_.reset();
        }
    }

    bool has_transport() const { return transport_ != nullptr; }

private:
    std::string carrier_path_;
    TCPServer server_;
    std::unique_ptr<TCPTransport> transport_;
};

// In-process TCP pair backing a ClientSession. The session owns the
// "server-side" transport (where messages forwarded from a backend land);
// the test reads from the "client-side" transport to assert delivery.
struct SessionPair {
    TCPServer server;
    std::unique_ptr<TCPTransport> client_side;  // remote (test side)
    std::shared_ptr<ClientSession> session;     // owns server-side transport

    SessionPair() {
        server.bind(0);
        server.start();

        std::future<std::unique_ptr<TCPTransport>> server_fut = std::async(
            std::launch::async, [this]() -> std::unique_ptr<TCPTransport> {
                AcceptedSocket sock = server.accept(TEST_TIMEOUT_SECS);
                if (!sock.is_valid()) {
                    throw std::runtime_error("SessionPair: accept timed out");
                }
                auto tp = TCPTransport::from_accepted(std::move(sock));
                tp->start();
                return tp;
            });

        client_side = std::make_unique<TCPTransport>();
        client_side->start();
        if (!client_side->connect("127.0.0.1", server.local_port(), TEST_TIMEOUT_SECS)) {
            throw std::runtime_error("SessionPair: client connect failed");
        }

        auto server_side = server_fut.get();
        session = std::make_shared<ClientSession>(std::move(server_side));
        // Sessions are admitted as active before forward callbacks fire;
        // simulate that here.
        session->active.store(true, std::memory_order_release);
    }

    ~SessionPair() {
        if (client_side) client_side->stop();
        // session destructor stops its server-side transport.
        server.stop();
    }

    // Receive one MessageV1 from the client-side socket (i.e. what the proxy
    // would deliver to the connected client).
    bool try_recv_message(pb::MessageV1& out, double timeout_secs) {
        std::vector<uint8_t> buf(RECV_BUF_SIZE);
        RecvResult result = client_side->recv(buf.data(), buf.size(), timeout_secs);
        if (result.status != RecvStatus::Success || result.bytes == 0) {
            return false;
        }
        pb::Envelope env;
        if (!env.ParseFromArray(buf.data(), static_cast<int>(result.bytes))) {
            return false;
        }
        if (!env.has_message_v1()) return false;
        out = env.message_v1();
        return true;
    }
};

}  // namespace

class ProxyBackendHandlerTest : public ::testing::Test {
protected:
    void SetUp() override {
        backend_ = std::make_unique<MockBackend>(CARRIER_PATH_A);
        handler_ = std::make_unique<ProxyBackendHandler>(&log_mutex_);
    }

    void TearDown() override {
        if (started_) {
            handler_->stop();
        }
        handler_.reset();
        backend_.reset();
    }

    void add_backend_a() {
        std::future<void> handshake = std::async(std::launch::async, [this]() {
            backend_->accept_connection();
            backend_->serve_add_backend_handshake_tcp_fallback();
        });
        handler_->add_backend("127.0.0.1", backend_->port(), std::nullopt, std::nullopt);
        handshake.get();
    }

    void start_handler(size_t backend_count) {
        coord_.configure(backend_count);
        handler_->start(coord_, [this](ClientSession& sess, const std::string& desc) {
            error_callback_count_.fetch_add(1, std::memory_order_release);
            {
                std::lock_guard<std::mutex> lk(error_mutex_);
                last_error_session_ = &sess;
                last_error_description_ = desc;
            }
        });
        started_ = true;
    }

    std::mutex log_mutex_;
    std::unique_ptr<MockBackend> backend_;
    std::unique_ptr<ProxyBackendHandler> handler_;
    RunCoordinator coord_;
    bool started_{false};

    // Captured error_to_client invocations.
    std::atomic<int> error_callback_count_{0};
    std::mutex error_mutex_;
    ClientSession* last_error_session_{nullptr};
    std::string last_error_description_;
};

TEST_F(ProxyBackendHandlerTest, AddBackend_PopulatesPathMap) {
    add_backend_a();
    start_handler(/*backend_count=*/1);

    BackendDevice* found = handler_->find_backend_for_path(CARRIER_PATH_A);
    ASSERT_NE(found, nullptr);
    EXPECT_EQ(found->host, "127.0.0.1");
    EXPECT_EQ(found->port, backend_->port());
}

TEST_F(ProxyBackendHandlerTest, AddBackend_AfterStart_Throws) {
    add_backend_a();
    start_handler(/*backend_count=*/1);

    EXPECT_THROW(handler_->add_backend("127.0.0.1", 1, std::nullopt, std::nullopt), std::logic_error);
}

TEST_F(ProxyBackendHandlerTest, Broadcast_AllSucceed) {
    add_backend_a();
    start_handler(/*backend_count=*/1);

    // Run a single resetCommand broadcast; the mock backend serves it on a
    // background thread.
    std::future<void> backend_serves = std::async(std::launch::async, [this]() {
        pb::MessageV1 req = backend_->recv_message();
        ASSERT_TRUE(req.has_reset_command());
        backend_->send_message(backend_->make_reset_response(req.id()));
    });

    auto factory = [](BackendDevice&) {
        pb::MessageV1 msg;
        msg.set_id("req-1");
        msg.mutable_reset_command();
        return msg;
    };

    BroadcastResult result = handler_->broadcast_to_backends(
        handler_->targets(),
        factory,
        /*timeout_secs=*/TEST_TIMEOUT_SECS,
        /*include_responses=*/true);

    backend_serves.get();

    EXPECT_FALSE(result.had_error);
    EXPECT_EQ(result.responses.size(), 1u);
    EXPECT_TRUE(result.responses[0].has_reset_response());
}

TEST_F(ProxyBackendHandlerTest, Broadcast_OneBackendDisconnected_ReportsError) {
    add_backend_a();
    start_handler(/*backend_count=*/1);

    // Disconnect the mock backend's transport. The handler's control channel
    // should observe the disconnect; broadcast_to_backends sees
    // is_connected() == false and short-circuits with had_error=true.
    backend_->disconnect();

    // Allow the proxy-side control channel to notice the EOF.
    std::this_thread::sleep_for(std::chrono::milliseconds(200));

    auto factory = [](BackendDevice&) {
        pb::MessageV1 msg;
        msg.set_id("req-disc");
        msg.mutable_reset_command();
        return msg;
    };

    BroadcastResult result = handler_->broadcast_to_backends(
        handler_->targets(),
        factory,
        /*timeout_secs=*/1.0,
        /*include_responses=*/false);

    EXPECT_TRUE(result.had_error);
    EXPECT_NE(result.error_text.find("127.0.0.1"), std::string::npos)
        << "error_text should reference the backend host, got: " << result.error_text;
}

TEST_F(ProxyBackendHandlerTest, SetActiveSession_InstallsForward) {
    add_backend_a();
    start_handler(/*backend_count=*/1);

    SessionPair pair;
    handler_->set_active_session(pair.session);

    // Send a RunDataMessage through the backend's TCP fallback path; the
    // installed forward callback should deliver it to the session transport.
    pb::MessageV1 data_msg;
    data_msg.mutable_run_data_message();
    backend_->send_message(data_msg);

    pb::MessageV1 received;
    bool got = pair.try_recv_message(received, /*timeout_secs=*/3.0);
    ASSERT_TRUE(got) << "Session did not receive forwarded RunDataMessage";
    EXPECT_TRUE(received.has_run_data_message());
}

TEST_F(ProxyBackendHandlerTest, SetActiveSession_Empty_ClearsForward) {
    add_backend_a();
    start_handler(/*backend_count=*/1);

    SessionPair pair;
    handler_->set_active_session(pair.session);

    // Clear by passing an empty weak_ptr.
    handler_->set_active_session({});

    // After clearing, both the data forward callback AND the control-channel
    // RunStateChangeMessage callback must be uninstalled. Send both shapes.
    pb::MessageV1 data_msg;
    data_msg.mutable_run_data_message();
    backend_->send_message(data_msg);

    pb::MessageV1 state_msg = backend_->make_run_state_notification(pb::DONE);
    backend_->send_message(state_msg);

    pb::MessageV1 received;
    bool got = pair.try_recv_message(received, /*timeout_secs=*/0.5);
    EXPECT_FALSE(got) << "Session received a message after set_active_session({}) cleared "
                         "the forward callbacks";
}

TEST_F(ProxyBackendHandlerTest, SetActiveSession_Churn) {
    add_backend_a();
    start_handler(/*backend_count=*/1);

    SessionPair pair_a;
    SessionPair pair_b;

    handler_->set_active_session(pair_a.session);
    handler_->set_active_session({});
    handler_->set_active_session(pair_b.session);

    pb::MessageV1 data_msg;
    data_msg.mutable_run_data_message();
    backend_->send_message(data_msg);

    pb::MessageV1 received_b;
    ASSERT_TRUE(pair_b.try_recv_message(received_b, /*timeout_secs=*/3.0))
        << "Session B did not receive the message after churn";
    EXPECT_TRUE(received_b.has_run_data_message());

    // A must NOT have received it. Use a short timeout — we do not want
    // to extend total runtime if the assertion already holds.
    pb::MessageV1 received_a;
    EXPECT_FALSE(pair_a.try_recv_message(received_a, /*timeout_secs=*/0.3))
        << "Session A received a message after being demoted";
}

TEST_F(ProxyBackendHandlerTest, RunStateChange_Done_AdvancesCoordinator) {
    // Two backends so that on_done() returns true only after both DONEs.
    auto backend_b = std::make_unique<MockBackend>(CARRIER_PATH_B);

    std::future<void> handshake_a = std::async(std::launch::async, [this]() {
        backend_->accept_connection();
        backend_->serve_add_backend_handshake_tcp_fallback();
    });
    std::future<void> handshake_b = std::async(std::launch::async, [&]() {
        backend_b->accept_connection();
        backend_b->serve_add_backend_handshake_tcp_fallback();
    });

    handler_->add_backend("127.0.0.1", backend_->port(), std::nullopt, std::nullopt);
    handshake_a.get();
    handler_->add_backend("127.0.0.1", backend_b->port(), std::nullopt, std::nullopt);
    handshake_b.get();

    start_handler(/*backend_count=*/2);

    SessionPair pair;
    handler_->set_active_session(pair.session);

    backend_->send_message(backend_->make_run_state_notification(pb::DONE));
    backend_b->send_message(backend_b->make_run_state_notification(pb::DONE));

    // The session's done_received flag flips inside the forward lambda only
    // when on_done() returns true (i.e. the last backend's DONE arrived).
    auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(3);
    while (!pair.session->done_received.load(std::memory_order_acquire) &&
           std::chrono::steady_clock::now() < deadline) {
        std::this_thread::sleep_for(std::chrono::milliseconds(20));
    }
    EXPECT_TRUE(pair.session->done_received.load(std::memory_order_acquire))
        << "Session done_received was not set; on_done() never returned true "
           "after both DONE messages were forwarded";
}

TEST_F(ProxyBackendHandlerTest, RunStateChange_Error_InvokesErrorCallback) {
    add_backend_a();
    start_handler(/*backend_count=*/1);

    SessionPair pair;
    handler_->set_active_session(pair.session);

    pb::MessageV1 err_state;
    err_state.mutable_run_state_change_message()->set_new_(pb::ERROR);
    err_state.mutable_run_state_change_message()->set_reason("simulated fault");
    backend_->send_message(err_state);

    auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(3);
    while (error_callback_count_.load(std::memory_order_acquire) == 0 && std::chrono::steady_clock::now() < deadline) {
        std::this_thread::sleep_for(std::chrono::milliseconds(20));
    }

    EXPECT_GE(error_callback_count_.load(std::memory_order_acquire), 1);
    {
        std::lock_guard<std::mutex> lk(error_mutex_);
        EXPECT_NE(last_error_description_.find("Backend device error"), std::string::npos)
            << "expected backend error description, got: " << last_error_description_;
        EXPECT_NE(last_error_description_.find("simulated fault"), std::string::npos)
            << "expected reason in description, got: " << last_error_description_;
    }
}

TEST_F(ProxyBackendHandlerTest, StaleRunCallback_NotFiltered) {
    // Regression fence: forward callbacks installed before start_run() are
    // NOT tagged with the run id at install time, so DONE messages they
    // forward after the run id bumps still advance the coordinator counter.
    // Two backends make this observable: with no filtering, both DONEs reach
    // on_done() and the second flips done_received.
    auto backend_b = std::make_unique<MockBackend>(CARRIER_PATH_B);

    std::future<void> handshake_a = std::async(std::launch::async, [this]() {
        backend_->accept_connection();
        backend_->serve_add_backend_handshake_tcp_fallback();
    });
    std::future<void> handshake_b = std::async(std::launch::async, [&]() {
        backend_b->accept_connection();
        backend_b->serve_add_backend_handshake_tcp_fallback();
    });

    handler_->add_backend("127.0.0.1", backend_->port(), std::nullopt, std::nullopt);
    handshake_a.get();
    handler_->add_backend("127.0.0.1", backend_b->port(), std::nullopt, std::nullopt);
    handshake_b.get();

    start_handler(/*backend_count=*/2);

    SessionPair pair;
    handler_->set_active_session(pair.session);

    // Stale-run boundary: bump the run id while the lambdas captured above
    // remain in place.
    coord_.start_run();

    backend_->send_message(backend_->make_run_state_notification(pb::DONE));
    backend_b->send_message(backend_b->make_run_state_notification(pb::DONE));

    auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(3);
    while (!pair.session->done_received.load(std::memory_order_acquire) &&
           std::chrono::steady_clock::now() < deadline) {
        std::this_thread::sleep_for(std::chrono::milliseconds(20));
    }

    EXPECT_TRUE(pair.session->done_received.load(std::memory_order_acquire))
        << "DONEs forwarded by lambdas installed before start_run() should "
           "still advance done_count_ to backend_count and flip done_received";
}

TEST_F(ProxyBackendHandlerTest, Reconnect_PreservesForwardCallback) {
    add_backend_a();
    start_handler(/*backend_count=*/1);

    SessionPair pair;
    handler_->set_active_session(pair.session);

    backend_->disconnect();
    std::this_thread::sleep_for(std::chrono::milliseconds(100));

    std::future<void> reconnect_serve = std::async(std::launch::async, [this]() {
        backend_->accept_connection(/*timeout_secs=*/15.0);
        backend_->serve_reconnect_handshake_tcp_fallback();
    });

    auto* backend_dev = handler_->find_backend_for_path(CARRIER_PATH_A);
    ASSERT_NE(backend_dev, nullptr);
    bool ok = handler_->reconnect_backend(*backend_dev, std::chrono::milliseconds{15000});
    ASSERT_TRUE(ok) << "reconnect_backend should succeed";
    reconnect_serve.get();

    // After reconnect, the data channel's forward callback survives (it is
    // re-installed implicitly because the data channel object is reused).
    pb::MessageV1 data_msg;
    data_msg.mutable_run_data_message();
    backend_->send_message(data_msg);

    pb::MessageV1 received;
    bool got = pair.try_recv_message(received, /*timeout_secs=*/3.0);
    EXPECT_TRUE(got) << "After reconnect, forward callback no longer delivers messages "
                        "to the active session";
    if (got) {
        EXPECT_TRUE(received.has_run_data_message());
    }
}

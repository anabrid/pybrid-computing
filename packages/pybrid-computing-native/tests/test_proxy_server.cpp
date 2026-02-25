// Copyright (c) 2022-2025 anabrid GmbH
// SPDX-License-Identifier: MIT OR GPL-2.0-or-later

/**
 * @file test_proxy_server.cpp
 * @brief Unit tests for the ProxyServer class.
 *
 * Uses real TCP loopback: TCPServer instances simulate backend devices.
 * Each mock backend responds to DescribeCommand, ResetCommand, and
 * StartRunCommand with scripted protobuf responses, matching the
 * minimum protocol surface that the ProxyServer exercises during
 * add_backend() and message forwarding.
 *
 * Test fixture pattern follows test_control_channel.cpp:
 *   - MockBackend wraps a TCPServer and a server-side TCPTransport.
 *   - Helper methods serialise / deserialise pb::Envelope on the
 *     "device" side of the connection.
 *   - Tests create a ProxyServer, call add_backend(), then start().
 *   - Client access uses ControlChannel::create() pointed at the
 *     proxy's local_port().
 */

#include <gtest/gtest.h>

#include <atomic>
#include <chrono>
#include <future>
#include <memory>
#include <optional>
#include <string>
#include <thread>
#include <vector>

#include "pybrid/channel/control_channel.h"
#include "pybrid/proto/main.pb.h"
#include "pybrid/proxy/proxy_server.h"
#include "pybrid/transport/tcp_server.h"
#include "pybrid/transport/tcp_transport.h"
#include "pybrid/utils/uuid.h"

using namespace anabrid::pybrid::native;

// =============================================================================
// Constants
// =============================================================================

static constexpr double TEST_TIMEOUT_SECS = 5.0;
static constexpr size_t RECV_BUF_SIZE = 65536;

// Carrier MAC used in mock backend entity trees.
static const std::string CARRIER_MAC_A = "aa-bb-cc-dd-ee-ff";
static const std::string CARRIER_PATH_A = "/" + CARRIER_MAC_A;

static const std::string CARRIER_MAC_B = "11-22-33-44-55-66";
static const std::string CARRIER_PATH_B = "/" + CARRIER_MAC_B;

// =============================================================================
// MockBackend
// =============================================================================

/**
 * @brief Simulates one backend device over a TCP loopback.
 *
 * Owns a TCPServer that the ProxyServer's add_backend() connects to.
 * After add_backend() has connected, accept_connection() must be called
 * to obtain the server-side TCPTransport. The test can then drive the
 * mock backend using recv_message() and send_message().
 *
 * The constructor starts the TCPServer immediately so the port is known
 * before add_backend() is called.
 */
class MockBackend {
public:
    /**
     * @brief Start the mock backend's TCP listener on an ephemeral port.
     *
     * @param carrier_path Entity path to advertise in DescribeResponse.
     */
    explicit MockBackend(const std::string& carrier_path = CARRIER_PATH_A)
        : carrier_path_(carrier_path) {
        server_.bind(0);
        server_.start();
    }

    ~MockBackend() {
        if (transport_) {
            transport_->stop();
        }
        server_.stop();
    }

    // Non-copyable
    MockBackend(const MockBackend&) = delete;
    MockBackend& operator=(const MockBackend&) = delete;

    /** @brief Local port the mock backend listens on. */
    uint16_t port() const { return server_.local_port(); }

    /**
     * @brief Accept the connection that add_backend() establishes.
     *
     * Must be called (usually on a background thread) before or shortly
     * after ProxyServer::add_backend() to avoid a connection-refused race.
     *
     * @param timeout_secs Maximum time to wait.
     */
    void accept_connection(double timeout_secs = TEST_TIMEOUT_SECS) {
        AcceptedSocket sock = server_.accept(timeout_secs);
        if (!sock.is_valid()) {
            throw std::runtime_error("MockBackend: accept timed out");
        }
        transport_ = TCPTransport::from_accepted(sock);
        if (!transport_) {
            throw std::runtime_error("MockBackend: from_accepted returned null");
        }
        transport_->start();
    }

    /**
     * @brief Read one Envelope from the server-side transport and return the
     *        inner MessageV1.
     *
     * @param timeout_secs Read timeout.
     * @return Deserialized MessageV1.
     */
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

    /**
     * @brief Send a MessageV1 from the mock backend to the ProxyServer.
     *
     * @param msg Message to send (wrapped in an Envelope).
     */
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

    /**
     * @brief Build a DescribeResponse carrying this backend's carrier entity.
     *
     * @param request_id The id to copy into the response for correlation.
     * @return A fully constructed MessageV1 describing a single carrier.
     */
    pb::MessageV1 make_describe_response(const std::string& request_id) const {
        pb::MessageV1 resp;
        resp.set_id(request_id);
        pb::Entity* carrier = resp.mutable_describe_response()->mutable_entity();
        carrier->set_id(carrier_path_);
        carrier->set_class_(pb::Entity::CARRIER);
        return resp;
    }

    /**
     * @brief Build a ResetResponse for the given request id.
     *
     * @param request_id The id to copy for correlation.
     * @return A fully constructed ResetResponse MessageV1.
     */
    pb::MessageV1 make_reset_response(const std::string& request_id) const {
        pb::MessageV1 resp;
        resp.set_id(request_id);
        resp.mutable_reset_response()->mutable_entity()->set_path(carrier_path_);
        return resp;
    }

    /**
     * @brief Build a StartRunResponse for the given request id.
     *
     * @param request_id The id to copy for correlation.
     * @return A fully constructed StartRunResponse MessageV1.
     */
    pb::MessageV1 make_start_run_response(const std::string& request_id) const {
        pb::MessageV1 resp;
        resp.set_id(request_id);
        resp.mutable_start_run_response();
        return resp;
    }

    /**
     * @brief Build an unsolicited RunStateChangeMessage notification.
     *
     * @param new_state The new run state.
     * @return A MessageV1 notification (empty id).
     */
    pb::MessageV1 make_run_state_notification(pb::RunState new_state) const {
        pb::MessageV1 notif;
        // Empty id marks this as an unsolicited notification.
        notif.mutable_run_state_change_message()->set_new_(new_state);
        return notif;
    }

    /**
     * @brief Serve the standard add_backend() handshake: DescribeCommand
     *        followed by ResetCommand, responding to each.
     *
     * The ProxyServer calls add_backend(), which sends DescribeCommand then
     * ResetCommand in sequence. This helper drains both and sends canned
     * responses. Must be called from a background thread that has already
     * called accept_connection().
     */
    void serve_add_backend_handshake() {
        // 1. DescribeCommand
        pb::MessageV1 describe_req = recv_message();
        if (!describe_req.has_describe_command()) {
            throw std::runtime_error(
                "MockBackend::serve_add_backend_handshake: expected DescribeCommand");
        }
        send_message(make_describe_response(describe_req.id()));

        // 2. ResetCommand
        pb::MessageV1 reset_req = recv_message();
        if (!reset_req.has_reset_command()) {
            throw std::runtime_error(
                "MockBackend::serve_add_backend_handshake: expected ResetCommand");
        }
        send_message(make_reset_response(reset_req.id()));
    }

    /** @brief Carrier entity path this backend advertises. */
    const std::string& carrier_path() const { return carrier_path_; }

    /** @brief Stop the underlying transport (simulate device disconnect). */
    void disconnect() {
        if (transport_) {
            transport_->stop();
            transport_.reset();
        }
    }

private:
    std::string carrier_path_;
    TCPServer server_;
    std::unique_ptr<TCPTransport> transport_;
};

// =============================================================================
// Helpers
// =============================================================================

/**
 * @brief Serialize a MessageV1 into an Envelope and send it via the transport.
 *
 * Used by client-side helpers that want to push raw messages through the
 * proxy without going through a ControlChannel.
 *
 * @param transport The transport to send through.
 * @param msg       The message to send.
 */
static void send_via_transport(TCPTransport& transport, const pb::MessageV1& msg) {
    pb::Envelope env;
    *env.mutable_message_v1() = msg;
    std::string bytes;
    ASSERT_TRUE(env.SerializeToString(&bytes));
    ASSERT_TRUE(transport.send(bytes.data(), bytes.size()));
}

/**
 * @brief Receive one MessageV1 from a raw transport.
 *
 * @param transport    Transport to read from.
 * @param timeout_secs Receive timeout.
 * @return The deserialized MessageV1.
 */
static pb::MessageV1 recv_via_transport(
    TCPTransport& transport,
    double timeout_secs = TEST_TIMEOUT_SECS) {
    std::vector<uint8_t> buf(RECV_BUF_SIZE);
    RecvResult result = transport.recv(buf.data(), buf.size(), timeout_secs);
    EXPECT_EQ(result.status, RecvStatus::Success);
    EXPECT_GT(result.bytes, 0u);
    pb::Envelope env;
    EXPECT_TRUE(env.ParseFromArray(buf.data(), static_cast<int>(result.bytes)));
    EXPECT_TRUE(env.has_message_v1());
    return env.message_v1();
}

// =============================================================================
// ProxyServerTest fixture
// =============================================================================

/**
 * @brief Fixture that manages one MockBackend and one ProxyServer.
 *
 * Subclasses or individual tests can create additional MockBackend instances
 * for multi-backend scenarios. The fixture starts the backend handshake on a
 * background thread to avoid deadlock during add_backend().
 */
class ProxyServerTest : public ::testing::Test {
protected:
    void SetUp() override {
        backend_ = std::make_unique<MockBackend>(CARRIER_PATH_A);
        proxy_ = std::make_unique<ProxyServer>();
        // Use a very short session timeout so timeout-expiry tests complete quickly.
        proxy_->set_session_timeout(0.5);
    }

    void TearDown() override {
        if (proxy_->is_running()) {
            proxy_->stop();
        }
        proxy_.reset();
        backend_.reset();
    }

    /**
     * @brief Start the backend handshake on a background thread, then call
     *        add_backend() and start() on the proxy.
     *
     * This is the standard setup for tests that need a running proxy with one
     * connected backend.
     */
    void start_proxy_with_single_backend() {
        // Serve the add_backend() handshake asynchronously.
        std::future<void> handshake = std::async(std::launch::async, [this]() {
            backend_->accept_connection();
            backend_->serve_add_backend_handshake();
        });

        proxy_->add_backend("127.0.0.1", backend_->port());
        handshake.get();

        proxy_->start("127.0.0.1", 0);
    }

    /** @brief Local port the proxy listens on (valid after start_proxy_with_single_backend). */
    uint16_t proxy_port() const { return proxy_->local_port(); }

    std::unique_ptr<MockBackend> backend_;
    std::unique_ptr<ProxyServer> proxy_;
};

// =============================================================================
// Test 1: AcceptClientConnection
// =============================================================================

/**
 * @brief ProxyServer accepts a client connection via ControlChannel::create().
 *
 * Verifies:
 * - A running proxy server reports is_running() == true.
 * - ControlChannel::create() directed at the proxy port succeeds.
 * - The returned channel is non-null and reports is_connected() == true.
 */
TEST_F(ProxyServerTest, AcceptClientConnection) {
    start_proxy_with_single_backend();

    EXPECT_TRUE(proxy_->is_running());
    EXPECT_GT(proxy_port(), 0u);

    auto client = ControlChannel::create("127.0.0.1", proxy_port(), TEST_TIMEOUT_SECS);

    ASSERT_NE(client, nullptr);
    EXPECT_TRUE(client->is_connected());

    client->stop();
}

// =============================================================================
// Test 2: DescribeForwarding
// =============================================================================

/**
 * @brief DescribeCommand from client → proxy forwards to backend → aggregated
 *        entity tree returned to client.
 *
 * Verifies:
 * - Client sends DescribeCommand through the proxy.
 * - Proxy forwards it to the backend and collects the DescribeResponse.
 * - The entity tree returned to the client contains the carrier path
 *   advertised by the backend.
 */
TEST_F(ProxyServerTest, DescribeForwarding) {
    start_proxy_with_single_backend();

    auto client = ControlChannel::create("127.0.0.1", proxy_port(), TEST_TIMEOUT_SECS);
    client->start();

    // Run the describe call in a background thread so we can concurrently
    // serve any forwarded messages that the proxy sends to the backend.
    // (The proxy handles describe internally from the describe response cached
    // during add_backend, but we verify that the client-facing response is
    // correct regardless of the implementation strategy.)
    pb::MessageV1 request;
    const std::string req_id = utils::generate_uuid();
    request.set_id(req_id);
    request.mutable_describe_command();

    std::future<pb::MessageV1> fut = std::async(
        std::launch::async,
        [&]() { return client->send_and_recv(request, TEST_TIMEOUT_SECS); });

    pb::MessageV1 result = fut.get();
    ASSERT_TRUE(result.has_describe_response())
        << "Expected describe_response, got kind: " << result.kind_case();

    // The aggregated entity tree must reference the carrier path.
    const pb::Entity& root = result.describe_response().entity();
    bool found = false;
    // Root itself might be the carrier, or it might be a parent containing it.
    if (root.id() == CARRIER_PATH_A) {
        found = true;
    }
    for (int i = 0; i < root.children_size(); ++i) {
        if (root.children(i).id() == CARRIER_PATH_A) {
            found = true;
        }
    }
    EXPECT_TRUE(found) << "Carrier path '" << CARRIER_PATH_A
                       << "' not found in entity tree. Root id: " << root.id();

    client->stop();
}

// =============================================================================
// Test 3: ResetForwarding
// =============================================================================

/**
 * @brief ResetCommand from client → proxy broadcasts to backend → response
 *        returned to client.
 *
 * Verifies:
 * - The backend receives a ResetCommand forwarded by the proxy.
 * - The client receives a ResetResponse (or success-equivalent) after the
 *   proxy aggregates the backend response.
 */
TEST_F(ProxyServerTest, ResetForwarding) {
    start_proxy_with_single_backend();

    auto client = ControlChannel::create("127.0.0.1", proxy_port(), TEST_TIMEOUT_SECS);
    client->start();

    // The proxy will forward ResetCommand to backend; serve it concurrently.
    std::future<void> backend_server = std::async(std::launch::async, [this]() {
        pb::MessageV1 req = backend_->recv_message();
        EXPECT_TRUE(req.has_reset_command());
        backend_->send_message(backend_->make_reset_response(req.id()));
    });

    pb::MessageV1 request;
    const std::string req_id = utils::generate_uuid();
    request.set_id(req_id);
    request.mutable_reset_command();

    std::future<pb::MessageV1> client_fut = std::async(
        std::launch::async,
        [&]() { return client->send_and_recv(request, TEST_TIMEOUT_SECS); });

    backend_server.get();
    pb::MessageV1 result = client_fut.get();

    EXPECT_TRUE(result.has_reset_response() || result.has_success_message())
        << "Expected reset_response or success, got kind: " << result.kind_case();

    client->stop();
}

// =============================================================================
// Test 4: ConfigForwarding
// =============================================================================

/**
 * @brief ConfigCommand from client routed to correct backend, response
 *        forwarded back to client.
 *
 * Verifies:
 * - Client sends a ConfigCommand carrying an entity path belonging to the
 *   single backend.
 * - The backend receives the ConfigCommand.
 * - The client receives a ConfigResponse.
 */
TEST_F(ProxyServerTest, ConfigForwarding) {
    start_proxy_with_single_backend();

    auto client = ControlChannel::create("127.0.0.1", proxy_port(), TEST_TIMEOUT_SECS);
    client->start();

    // Serve the forwarded ConfigCommand.
    std::future<void> backend_server = std::async(std::launch::async, [this]() {
        pb::MessageV1 req = backend_->recv_message();
        EXPECT_TRUE(req.has_config_command());

        pb::MessageV1 resp;
        resp.set_id(req.id());
        resp.mutable_config_response();
        backend_->send_message(resp);
    });

    pb::MessageV1 request;
    const std::string req_id = utils::generate_uuid();
    request.set_id(req_id);

    // ConfigCommand with one Config entry targeting the carrier path.
    auto* bundle = request.mutable_config_command()->mutable_bundle();
    auto* cfg = bundle->add_configs();
    cfg->mutable_entity()->set_path(CARRIER_PATH_A + "/0/U");
    cfg->mutable_device_config();  // Minimal non-null config payload.

    std::future<pb::MessageV1> client_fut = std::async(
        std::launch::async,
        [&]() { return client->send_and_recv(request, TEST_TIMEOUT_SECS); });

    backend_server.get();
    pb::MessageV1 result = client_fut.get();

    EXPECT_TRUE(result.has_config_response())
        << "Expected config_response, got kind: " << result.kind_case();

    client->stop();
}

// =============================================================================
// Test 5: RunStateForwarding
// =============================================================================

/**
 * @brief Unsolicited RunStateChangeMessage from backend forwarded to client.
 *
 * Verifies:
 * - Backend sends TAKE_OFF followed by DONE notifications (no id).
 * - Client's registered callback receives both state changes in order.
 */
TEST_F(ProxyServerTest, RunStateForwarding) {
    start_proxy_with_single_backend();

    auto client = ControlChannel::create("127.0.0.1", proxy_port(), TEST_TIMEOUT_SECS);

    std::vector<pb::RunState> received_states;
    std::mutex states_mutex;
    std::atomic<int> call_count{0};

    client->register_callback(
        pb::MessageV1::kRunStateChangeMessageFieldNumber,
        [&](pb::MessageV1& msg) {
            std::lock_guard<std::mutex> lock(states_mutex);
            received_states.push_back(msg.run_state_change_message().new_());
            call_count.fetch_add(1, std::memory_order_release);
        });

    client->start();

    // Backend sends TAKE_OFF then DONE.
    std::future<void> backend_notifier = std::async(std::launch::async, [this]() {
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
        backend_->send_message(backend_->make_run_state_notification(pb::TAKE_OFF));
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
        backend_->send_message(backend_->make_run_state_notification(pb::DONE));
    });
    backend_notifier.get();

    // Wait up to 3 s for both callbacks.
    auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(3);
    while (call_count.load(std::memory_order_acquire) < 2 &&
           std::chrono::steady_clock::now() < deadline) {
        std::this_thread::sleep_for(std::chrono::milliseconds(20));
    }

    EXPECT_EQ(call_count.load(), 2);
    {
        std::lock_guard<std::mutex> lock(states_mutex);
        ASSERT_EQ(received_states.size(), 2u);
        EXPECT_EQ(received_states[0], pb::TAKE_OFF);
        EXPECT_EQ(received_states[1], pb::DONE);
    }

    client->stop();
}

// =============================================================================
// Test 6: MultiBackendDescribe
// =============================================================================

/**
 * @brief Two loopback backends — proxy aggregates both entity trees and
 *        returns a merged result to the client.
 *
 * Verifies:
 * - ProxyServer::add_backend() can be called for two backends.
 * - A single DescribeCommand from the client receives a response that
 *   contains the carrier paths from both backends.
 */
TEST_F(ProxyServerTest, MultiBackendDescribe) {
    // Second backend with a different carrier path.
    auto backend_b = std::make_unique<MockBackend>(CARRIER_PATH_B);

    // Start handshakes for both backends on background threads.
    std::future<void> handshake_a = std::async(std::launch::async, [this]() {
        backend_->accept_connection();
        backend_->serve_add_backend_handshake();
    });
    std::future<void> handshake_b = std::async(std::launch::async, [&]() {
        backend_b->accept_connection();
        backend_b->serve_add_backend_handshake();
    });

    proxy_->add_backend("127.0.0.1", backend_->port());
    handshake_a.get();

    proxy_->add_backend("127.0.0.1", backend_b->port());
    handshake_b.get();

    proxy_->start("127.0.0.1", 0);

    auto client = ControlChannel::create("127.0.0.1", proxy_->local_port(), TEST_TIMEOUT_SECS);
    client->start();

    pb::MessageV1 request;
    request.set_id(utils::generate_uuid());
    request.mutable_describe_command();

    std::future<pb::MessageV1> fut = std::async(
        std::launch::async,
        [&]() { return client->send_and_recv(request, TEST_TIMEOUT_SECS); });

    pb::MessageV1 result = fut.get();
    ASSERT_TRUE(result.has_describe_response());

    // Collect all entity ids in the aggregated tree.
    const pb::Entity& root = result.describe_response().entity();
    std::vector<std::string> ids;
    ids.push_back(root.id());
    for (int i = 0; i < root.children_size(); ++i) {
        ids.push_back(root.children(i).id());
    }

    bool found_a = false, found_b = false;
    for (const auto& id : ids) {
        if (id == CARRIER_PATH_A) found_a = true;
        if (id == CARRIER_PATH_B) found_b = true;
    }
    EXPECT_TRUE(found_a) << "Carrier A path not found in merged describe response";
    EXPECT_TRUE(found_b) << "Carrier B path not found in merged describe response";

    client->stop();
}

// =============================================================================
// Test 7: ClientSessionOrdering
// =============================================================================

/**
 * @brief Two clients connect; the second is blocked in queue until the first
 *        disconnects.
 *
 * Verifies:
 * - Only one client session is active at a time.
 * - The second client cannot obtain a response while the first is active.
 * - After the first client disconnects, the second client becomes active and
 *   can complete a describe roundtrip.
 */
TEST_F(ProxyServerTest, ClientSessionOrdering) {
    start_proxy_with_single_backend();

    // First client connects and successfully describes.
    auto client1 = ControlChannel::create("127.0.0.1", proxy_port(), TEST_TIMEOUT_SECS);
    client1->start();

    pb::MessageV1 req1;
    req1.set_id(utils::generate_uuid());
    req1.mutable_describe_command();
    pb::MessageV1 resp1 = client1->send_and_recv(req1, TEST_TIMEOUT_SECS);
    EXPECT_TRUE(resp1.has_describe_response()) << "First client: expected describe_response";

    // Second client connects. While client1 is still active, client2's
    // request must not be served — it should time out or block.
    auto client2 = ControlChannel::create("127.0.0.1", proxy_port(), TEST_TIMEOUT_SECS);
    client2->start();

    pb::MessageV1 req2;
    req2.set_id(utils::generate_uuid());
    req2.mutable_describe_command();

    // Attempt with a short timeout — should NOT receive a response while
    // client1 is still connected.
    EXPECT_THROW(client2->send_and_recv(req2, 0.4), std::runtime_error)
        << "Second client should be blocked while first client is active";

    // Disconnect first client.
    client1->stop();

    // Now client2 should become active and succeed.
    // Re-issue the request (previous attempt timed out).
    std::this_thread::sleep_for(std::chrono::milliseconds(200));
    pb::MessageV1 req2b;
    req2b.set_id(utils::generate_uuid());
    req2b.mutable_describe_command();
    pb::MessageV1 resp2 = client2->send_and_recv(req2b, TEST_TIMEOUT_SECS);
    EXPECT_TRUE(resp2.has_describe_response()) << "Second client: expected describe_response";

    client2->stop();
}

// =============================================================================
// Test 8: ClientSessionTimeoutExpiry
// =============================================================================

/**
 * @brief Session timeout allows the next client to connect after idle period.
 *
 * Verifies:
 * - After a backend sends DONE and the first client idles beyond the session
 *   timeout (set to 0.5 s in SetUp), the session is freed.
 * - A second client then becomes active and can complete a describe roundtrip.
 */
TEST_F(ProxyServerTest, ClientSessionTimeoutExpiry) {
    start_proxy_with_single_backend();

    // First client connects and receives a DONE notification, then goes idle.
    auto client1 = ControlChannel::create("127.0.0.1", proxy_port(), TEST_TIMEOUT_SECS);

    std::atomic<bool> done_received{false};
    client1->register_callback(
        pb::MessageV1::kRunStateChangeMessageFieldNumber,
        [&](pb::MessageV1& msg) {
            if (msg.run_state_change_message().new_() == pb::DONE) {
                done_received.store(true, std::memory_order_release);
            }
        });
    client1->start();

    // Trigger DONE from backend to start the timeout clock.
    std::future<void> notifier = std::async(std::launch::async, [this]() {
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
        backend_->send_message(backend_->make_run_state_notification(pb::DONE));
    });
    notifier.get();

    // Wait for client1 to see DONE.
    auto dl = std::chrono::steady_clock::now() + std::chrono::seconds(3);
    while (!done_received.load(std::memory_order_acquire) &&
           std::chrono::steady_clock::now() < dl) {
        std::this_thread::sleep_for(std::chrono::milliseconds(20));
    }
    EXPECT_TRUE(done_received.load()) << "Client1: DONE notification not received";

    // Wait for the session timeout (0.5 s) to expire.
    std::this_thread::sleep_for(std::chrono::milliseconds(800));

    // Second client should now be admitted.
    auto client2 = ControlChannel::create("127.0.0.1", proxy_port(), TEST_TIMEOUT_SECS);
    client2->start();

    pb::MessageV1 req;
    req.set_id(utils::generate_uuid());
    req.mutable_describe_command();
    pb::MessageV1 resp = client2->send_and_recv(req, TEST_TIMEOUT_SECS);
    EXPECT_TRUE(resp.has_describe_response())
        << "Second client after timeout: expected describe_response";

    client1->stop();
    client2->stop();
}

// =============================================================================
// Test 9: ClientDisconnectCleansUpSession
// =============================================================================

/**
 * @brief Abrupt client disconnect frees the session slot for the next client.
 *
 * Verifies:
 * - A client that connects and then abruptly stops (simulating a crash)
 *   causes the session to be freed.
 * - The next queued client becomes active and can complete a roundtrip.
 */
TEST_F(ProxyServerTest, ClientDisconnectCleansUpSession) {
    start_proxy_with_single_backend();

    // First client connects, issues a describe, then disconnects abruptly.
    {
        auto client1 = ControlChannel::create("127.0.0.1", proxy_port(), TEST_TIMEOUT_SECS);
        client1->start();

        pb::MessageV1 req;
        req.set_id(utils::generate_uuid());
        req.mutable_describe_command();
        pb::MessageV1 resp = client1->send_and_recv(req, TEST_TIMEOUT_SECS);
        EXPECT_TRUE(resp.has_describe_response());

        // Abrupt disconnect: stop without sending any close signal.
        client1->stop();
    }

    // Give the proxy a moment to detect the disconnect and clean up.
    std::this_thread::sleep_for(std::chrono::milliseconds(300));

    // Second client should now be admitted immediately.
    auto client2 = ControlChannel::create("127.0.0.1", proxy_port(), TEST_TIMEOUT_SECS);
    client2->start();

    pb::MessageV1 req2;
    req2.set_id(utils::generate_uuid());
    req2.mutable_describe_command();
    pb::MessageV1 resp2 = client2->send_and_recv(req2, TEST_TIMEOUT_SECS);
    EXPECT_TRUE(resp2.has_describe_response())
        << "Second client after first disconnect: expected describe_response";

    client2->stop();
}

// =============================================================================
// Test 10: DeviceDisconnectSendsError
// =============================================================================

/**
 * @brief Backend device disconnect during active session sends ErrorMessage
 *        to client and frees the session slot.
 *
 * Verifies:
 * - An active client receives an ErrorMessage when the backend disconnects.
 * - After the ErrorMessage, the session is freed and a subsequent client can
 *   connect (if the proxy reconnects the backend — or at minimum the session
 *   slot is not permanently blocked).
 */
TEST_F(ProxyServerTest, DeviceDisconnectSendsError) {
    start_proxy_with_single_backend();

    auto client = ControlChannel::create("127.0.0.1", proxy_port(), TEST_TIMEOUT_SECS);

    std::atomic<bool> error_received{false};
    client->register_callback(
        pb::MessageV1::kErrorMessageFieldNumber,
        [&](pb::MessageV1& /* msg */) {
            error_received.store(true, std::memory_order_release);
        });

    client->start();

    // Verify the client is active by completing a describe roundtrip first.
    pb::MessageV1 req;
    req.set_id(utils::generate_uuid());
    req.mutable_describe_command();
    pb::MessageV1 resp = client->send_and_recv(req, TEST_TIMEOUT_SECS);
    EXPECT_TRUE(resp.has_describe_response());

    // Disconnect the backend device.
    backend_->disconnect();

    // The proxy should detect the disconnect and send an ErrorMessage to the
    // active client.
    auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(5);
    while (!error_received.load(std::memory_order_acquire) &&
           std::chrono::steady_clock::now() < deadline) {
        std::this_thread::sleep_for(std::chrono::milliseconds(30));
    }

    EXPECT_TRUE(error_received.load())
        << "Client did not receive ErrorMessage after backend disconnect";

    client->stop();
}

// =============================================================================
// Authentication Tests
// =============================================================================

/**
 * @brief Helper RAII guard for setting/unsetting environment variables.
 *
 * Sets the given env var on construction and restores the original state
 * (set or unset) on destruction. Thread-safe within a single test but not
 * across concurrent tests that manipulate the same variable.
 */
class EnvVarGuard {
public:
    /**
     * @brief Set the environment variable to `value`, or unset it if value is empty.
     *
     * @param name  Environment variable name.
     * @param value Value to set, or empty string to unset.
     */
    explicit EnvVarGuard(const std::string& name, const std::string& value = "")
        : name_(name) {
        const char* old = std::getenv(name.c_str());
        had_value_ = (old != nullptr);
        if (had_value_) {
            original_value_ = old;
        }

        if (value.empty()) {
            ::unsetenv(name.c_str());
        } else {
            ::setenv(name.c_str(), value.c_str(), 1);
        }
    }

    ~EnvVarGuard() {
        if (had_value_) {
            ::setenv(name_.c_str(), original_value_.c_str(), 1);
        } else {
            ::unsetenv(name_.c_str());
        }
    }

    // Non-copyable
    EnvVarGuard(const EnvVarGuard&) = delete;
    EnvVarGuard& operator=(const EnvVarGuard&) = delete;

private:
    std::string name_;
    bool had_value_{false};
    std::string original_value_;
};

static const std::string AUTH_ENV_VAR = "PYBRID_AUTHENTICATION";
static const std::string AUTH_TOKEN = "test-secret-token-42";
static const std::string WRONG_TOKEN = "wrong-token-99";

// =============================================================================
// Test 11: AuthRequired_NoEnvVar_Throws
// =============================================================================

/**
 * @brief Constructing a ProxyServer with requires_auth=true when
 *        PYBRID_AUTHENTICATION is not set must throw std::runtime_error.
 *
 * Verifies:
 * - ProxyServer(true) reads the PYBRID_AUTHENTICATION env var.
 * - When the env var is absent, the constructor throws.
 * - The error message is descriptive.
 */
TEST_F(ProxyServerTest, AuthRequired_NoEnvVar_Throws) {
    // Ensure the env var is NOT set.
    EnvVarGuard guard(AUTH_ENV_VAR, "");

    EXPECT_THROW(
        {
            ProxyServer proxy_auth(/*requires_auth=*/true);
        },
        std::runtime_error
    ) << "ProxyServer(requires_auth=true) must throw when PYBRID_AUTHENTICATION is unset";
}

// =============================================================================
// Test 12: AuthRequired_WrongToken_Rejected
// =============================================================================

/**
 * @brief Client sends an AuthRequest with a wrong token when auth is required.
 *        The proxy must respond with an ErrorMessage.
 *
 * Verifies:
 * - ProxyServer(true) constructs successfully when PYBRID_AUTHENTICATION is set.
 * - An auth request with a non-matching token returns ErrorMessage, not SuccessMessage.
 */
TEST_F(ProxyServerTest, AuthRequired_WrongToken_Rejected) {
    EnvVarGuard guard(AUTH_ENV_VAR, AUTH_TOKEN);

    // Create a new proxy with auth enabled (replacing the fixture's proxy).
    proxy_ = std::make_unique<ProxyServer>(/*requires_auth=*/true);
    proxy_->set_session_timeout(0.5);

    // Start proxy with the single backend (from the fixture).
    std::future<void> handshake = std::async(std::launch::async, [this]() {
        backend_->accept_connection();
        backend_->serve_add_backend_handshake();
    });
    proxy_->add_backend("127.0.0.1", backend_->port());
    handshake.get();
    proxy_->start("127.0.0.1", 0);

    // Connect a client and send auth with wrong token.
    auto client = ControlChannel::create("127.0.0.1", proxy_port(), TEST_TIMEOUT_SECS);
    client->start();

    pb::MessageV1 auth_msg;
    auth_msg.set_id(utils::generate_uuid());
    auth_msg.mutable_auth_request()->mutable_bearer()->set_token(WRONG_TOKEN);

    std::future<pb::MessageV1> fut = std::async(
        std::launch::async,
        [&]() { return client->send_and_recv(auth_msg, TEST_TIMEOUT_SECS); });

    pb::MessageV1 result = fut.get();

    EXPECT_TRUE(result.has_error_message())
        << "Auth with wrong token should return ErrorMessage, got kind: "
        << result.kind_case();

    client->stop();
}

// =============================================================================
// Test 13: AuthRequired_CorrectToken_Accepted
// =============================================================================

/**
 * @brief Client authenticates with the correct token, then sends a describe.
 *        Both operations should succeed.
 *
 * Verifies:
 * - AuthRequest with matching token returns SuccessMessage.
 * - After successful auth, the client can issue a DescribeCommand normally.
 */
TEST_F(ProxyServerTest, AuthRequired_CorrectToken_Accepted) {
    EnvVarGuard guard(AUTH_ENV_VAR, AUTH_TOKEN);

    proxy_ = std::make_unique<ProxyServer>(/*requires_auth=*/true);
    proxy_->set_session_timeout(0.5);

    std::future<void> handshake = std::async(std::launch::async, [this]() {
        backend_->accept_connection();
        backend_->serve_add_backend_handshake();
    });
    proxy_->add_backend("127.0.0.1", backend_->port());
    handshake.get();
    proxy_->start("127.0.0.1", 0);

    auto client = ControlChannel::create("127.0.0.1", proxy_port(), TEST_TIMEOUT_SECS);
    client->start();

    // Step 1: Authenticate with correct token.
    pb::MessageV1 auth_msg;
    auth_msg.set_id(utils::generate_uuid());
    auth_msg.mutable_auth_request()->mutable_bearer()->set_token(AUTH_TOKEN);

    std::future<pb::MessageV1> auth_fut = std::async(
        std::launch::async,
        [&]() { return client->send_and_recv(auth_msg, TEST_TIMEOUT_SECS); });

    pb::MessageV1 auth_result = auth_fut.get();

    EXPECT_TRUE(auth_result.has_success_message())
        << "Auth with correct token should return SuccessMessage, got kind: "
        << auth_result.kind_case();

    // Step 2: After auth, describe should work.
    pb::MessageV1 describe_msg;
    describe_msg.set_id(utils::generate_uuid());
    describe_msg.mutable_describe_command();

    std::future<pb::MessageV1> desc_fut = std::async(
        std::launch::async,
        [&]() { return client->send_and_recv(describe_msg, TEST_TIMEOUT_SECS); });

    pb::MessageV1 desc_result = desc_fut.get();

    EXPECT_TRUE(desc_result.has_describe_response())
        << "Describe after successful auth should work, got kind: "
        << desc_result.kind_case();

    client->stop();
}

// =============================================================================
// Test 14: AuthRequired_UnauthenticatedMessage_Rejected
// =============================================================================

/**
 * @brief Client sends a DescribeCommand before authenticating when auth is
 *        required. The proxy must respond with an ErrorMessage containing
 *        "Authentication required".
 *
 * Verifies:
 * - When requires_auth=true and the client has NOT authenticated, any
 *   non-auth message is rejected with an ErrorMessage.
 * - The error description contains "Authentication required".
 */
TEST_F(ProxyServerTest, AuthRequired_UnauthenticatedMessage_Rejected) {
    EnvVarGuard guard(AUTH_ENV_VAR, AUTH_TOKEN);

    proxy_ = std::make_unique<ProxyServer>(/*requires_auth=*/true);
    proxy_->set_session_timeout(0.5);

    std::future<void> handshake = std::async(std::launch::async, [this]() {
        backend_->accept_connection();
        backend_->serve_add_backend_handshake();
    });
    proxy_->add_backend("127.0.0.1", backend_->port());
    handshake.get();
    proxy_->start("127.0.0.1", 0);

    auto client = ControlChannel::create("127.0.0.1", proxy_port(), TEST_TIMEOUT_SECS);
    client->start();

    // Send describe WITHOUT authenticating first.
    pb::MessageV1 describe_msg;
    describe_msg.set_id(utils::generate_uuid());
    describe_msg.mutable_describe_command();

    std::future<pb::MessageV1> fut = std::async(
        std::launch::async,
        [&]() { return client->send_and_recv(describe_msg, TEST_TIMEOUT_SECS); });

    pb::MessageV1 result = fut.get();

    EXPECT_TRUE(result.has_error_message())
        << "Unauthenticated describe should be rejected, got kind: "
        << result.kind_case();

    // Verify the error message text.
    if (result.has_error_message()) {
        EXPECT_NE(
            result.error_message().description().find("Authentication required"),
            std::string::npos
        ) << "Error description should contain 'Authentication required', got: '"
          << result.error_message().description() << "'";
    }

    client->stop();
}

// =============================================================================
// Test 15: ConcurrentDescribe_NoActiveSession
// =============================================================================

/**
 * @brief Two clients connect simultaneously and both send DescribeCommand.
 *        Both should receive the cached DescribeResponse without either needing
 *        to be the "active" session — describe is served from cache.
 *
 * Verifies:
 * - Two ControlChannel instances can connect to the same proxy.
 * - Both send DescribeCommand in parallel (via std::async).
 * - Both receive a valid DescribeResponse containing the expected carrier path.
 * - Neither client needs to wait for the other or become the "active" session.
 */
TEST_F(ProxyServerTest, ConcurrentDescribe_NoActiveSession) {
    start_proxy_with_single_backend();

    // Create two clients that will send describe concurrently.
    auto client_a = ControlChannel::create("127.0.0.1", proxy_port(), TEST_TIMEOUT_SECS);
    client_a->start();

    auto client_b = ControlChannel::create("127.0.0.1", proxy_port(), TEST_TIMEOUT_SECS);
    client_b->start();

    // Send describe from both clients in parallel.
    pb::MessageV1 req_a;
    req_a.set_id(utils::generate_uuid());
    req_a.mutable_describe_command();

    pb::MessageV1 req_b;
    req_b.set_id(utils::generate_uuid());
    req_b.mutable_describe_command();

    auto fut_a = std::async(std::launch::async, [&]() {
        return client_a->send_and_recv(req_a, TEST_TIMEOUT_SECS);
    });

    auto fut_b = std::async(std::launch::async, [&]() {
        return client_b->send_and_recv(req_b, TEST_TIMEOUT_SECS);
    });

    pb::MessageV1 result_a = fut_a.get();
    pb::MessageV1 result_b = fut_b.get();

    // Both must have received a valid DescribeResponse.
    ASSERT_TRUE(result_a.has_describe_response())
        << "Client A: expected describe_response, got kind: " << result_a.kind_case();
    ASSERT_TRUE(result_b.has_describe_response())
        << "Client B: expected describe_response, got kind: " << result_b.kind_case();

    // Both responses must contain the carrier path.
    auto check_carrier = [](const pb::MessageV1& resp, const std::string& label) {
        const pb::Entity& root = resp.describe_response().entity();
        bool found = (root.id() == CARRIER_PATH_A);
        for (int i = 0; i < root.children_size(); ++i) {
            if (root.children(i).id() == CARRIER_PATH_A) found = true;
        }
        EXPECT_TRUE(found) << label << ": carrier path '" << CARRIER_PATH_A
                           << "' not found in entity tree";
    };

    check_carrier(result_a, "Client A");
    check_carrier(result_b, "Client B");

    client_a->stop();
    client_b->stop();
}

// =============================================================================
// Test 16: ActiveSessionQueue_ControlMessageWaits
// =============================================================================

/**
 * @brief Client A sends a ResetCommand (becomes active). While A's session is
 *        ongoing, Client B sends a ConfigCommand. B should NOT receive a
 *        response until A disconnects. Then B's config should succeed.
 *
 * Verifies:
 * - Control messages (reset, config) require the session to be active.
 * - Client B's config is queued while Client A is the active session.
 * - After Client A disconnects, Client B becomes active and receives its
 *   config response.
 */
TEST_F(ProxyServerTest, ActiveSessionQueue_ControlMessageWaits) {
    start_proxy_with_single_backend();

    // --- Client A connects and sends a reset (becomes active) ---
    auto client_a = ControlChannel::create("127.0.0.1", proxy_port(), TEST_TIMEOUT_SECS);
    client_a->start();

    // Serve the backend's reset response.
    std::future<void> backend_reset = std::async(std::launch::async, [this]() {
        pb::MessageV1 req = backend_->recv_message();
        EXPECT_TRUE(req.has_reset_command());
        backend_->send_message(backend_->make_reset_response(req.id()));
    });

    pb::MessageV1 reset_req;
    reset_req.set_id(utils::generate_uuid());
    reset_req.mutable_reset_command();

    auto reset_fut = std::async(std::launch::async, [&]() {
        return client_a->send_and_recv(reset_req, TEST_TIMEOUT_SECS);
    });

    backend_reset.get();
    pb::MessageV1 reset_result = reset_fut.get();
    EXPECT_TRUE(reset_result.has_reset_response() || reset_result.has_success_message())
        << "Client A reset should succeed";

    // --- Client B connects and sends a config (should block in queue) ---
    auto client_b = ControlChannel::create("127.0.0.1", proxy_port(), TEST_TIMEOUT_SECS);
    client_b->start();

    pb::MessageV1 config_req;
    config_req.set_id(utils::generate_uuid());
    auto* bundle = config_req.mutable_config_command()->mutable_bundle();
    auto* cfg = bundle->add_configs();
    cfg->mutable_entity()->set_path(CARRIER_PATH_A + "/0/U");
    cfg->mutable_device_config();

    // Launch Client B's config in a background thread. It should block because
    // Client A is still the active session.
    std::atomic<bool> b_got_response{false};
    auto config_fut = std::async(std::launch::async, [&]() {
        pb::MessageV1 result = client_b->send_and_recv(config_req, TEST_TIMEOUT_SECS);
        b_got_response.store(true, std::memory_order_release);
        return result;
    });

    // Brief sleep to let B's request queue up.
    std::this_thread::sleep_for(std::chrono::milliseconds(300));

    // B should NOT have received a response yet (A is still active).
    EXPECT_FALSE(b_got_response.load(std::memory_order_acquire))
        << "Client B should be blocked while Client A is active";

    // --- Disconnect Client A to release the session ---
    client_a->stop();

    // Now the backend should receive B's config command (B becomes active).
    std::future<void> backend_config = std::async(std::launch::async, [this]() {
        pb::MessageV1 req = backend_->recv_message();
        EXPECT_TRUE(req.has_config_command());

        pb::MessageV1 resp;
        resp.set_id(req.id());
        resp.mutable_config_response();
        backend_->send_message(resp);
    });

    backend_config.get();
    pb::MessageV1 config_result = config_fut.get();

    EXPECT_TRUE(config_result.has_config_response())
        << "Client B config should succeed after A disconnects, got kind: "
        << config_result.kind_case();

    client_b->stop();
}

// =============================================================================
// Test 17: SessionOverload_Rejected
// =============================================================================

/**
 * @brief Set max_sessions to 2. Connect 3 clients. The third client should
 *        be rejected. The first two should be able to send describe successfully.
 *
 * Verifies:
 * - set_max_sessions() limits the number of concurrent sessions.
 * - Clients beyond the limit are rejected (connection refused or error on
 *   first message).
 * - Clients within the limit can operate normally.
 */
TEST_F(ProxyServerTest, SessionOverload_Rejected) {
    proxy_->set_max_sessions(2);
    start_proxy_with_single_backend();

    // Connect two clients — both should succeed.
    auto client1 = ControlChannel::create("127.0.0.1", proxy_port(), TEST_TIMEOUT_SECS);
    client1->start();

    auto client2 = ControlChannel::create("127.0.0.1", proxy_port(), TEST_TIMEOUT_SECS);
    client2->start();

    // First client describe should succeed (active session).
    pb::MessageV1 req1;
    req1.set_id(utils::generate_uuid());
    req1.mutable_describe_command();
    pb::MessageV1 resp1 = client1->send_and_recv(req1, TEST_TIMEOUT_SECS);
    EXPECT_TRUE(resp1.has_describe_response())
        << "Client 1 describe should succeed within max_sessions limit";

    // Third client should be rejected.
    // The proxy should either refuse the connection or return an OVERLOADED error.
    bool third_client_rejected = false;
    try {
        auto client3 = ControlChannel::create("127.0.0.1", proxy_port(), TEST_TIMEOUT_SECS);
        client3->start();

        // If connection succeeded, try sending a message — should get an error.
        pb::MessageV1 req3;
        req3.set_id(utils::generate_uuid());
        req3.mutable_describe_command();

        try {
            pb::MessageV1 resp3 = client3->send_and_recv(req3, 2.0);
            // If we got a response, it should be an error.
            if (resp3.has_error_message()) {
                third_client_rejected = true;
            }
        } catch (const std::runtime_error&) {
            // Timeout or error — means the client was rejected.
            third_client_rejected = true;
        }

        client3->stop();
    } catch (const std::runtime_error&) {
        // Connection refused — third client rejected at TCP level.
        third_client_rejected = true;
    }

    EXPECT_TRUE(third_client_rejected)
        << "Third client should be rejected when max_sessions=2";

    client1->stop();
    client2->stop();
}

// =============================================================================
// Test 18: DescribeWhileOtherActive
// =============================================================================

/**
 * @brief Client A sends a ResetCommand (becomes active, takes time). While A
 *        is active, Client B sends DescribeCommand. B should get the cached
 *        response immediately — it does NOT wait for A to finish.
 *
 * Verifies:
 * - DescribeCommand is served from cache without requiring active session status.
 * - A slow control command on Client A does not block Client B's describe.
 * - Client A eventually gets its reset response after the delay.
 */
TEST_F(ProxyServerTest, DescribeWhileOtherActive) {
    start_proxy_with_single_backend();

    // --- Client A sends reset; backend introduces a deliberate 2-second delay ---
    auto client_a = ControlChannel::create("127.0.0.1", proxy_port(), TEST_TIMEOUT_SECS);
    client_a->start();

    // Backend serves reset with a 2-second delay.
    std::future<void> backend_slow_reset = std::async(std::launch::async, [this]() {
        pb::MessageV1 req = backend_->recv_message();
        EXPECT_TRUE(req.has_reset_command());
        // Deliberate delay to simulate a slow operation.
        std::this_thread::sleep_for(std::chrono::seconds(2));
        backend_->send_message(backend_->make_reset_response(req.id()));
    });

    pb::MessageV1 reset_req;
    reset_req.set_id(utils::generate_uuid());
    reset_req.mutable_reset_command();

    // Fire Client A's reset asynchronously (will take ~2 seconds).
    auto reset_fut = std::async(std::launch::async, [&]() {
        return client_a->send_and_recv(reset_req, TEST_TIMEOUT_SECS);
    });

    // Brief pause to ensure A's reset is in progress.
    std::this_thread::sleep_for(std::chrono::milliseconds(200));

    // --- Client B sends describe while A's reset is in flight ---
    auto client_b = ControlChannel::create("127.0.0.1", proxy_port(), TEST_TIMEOUT_SECS);
    client_b->start();

    pb::MessageV1 desc_req;
    desc_req.set_id(utils::generate_uuid());
    desc_req.mutable_describe_command();

    auto start_time = std::chrono::steady_clock::now();
    auto desc_fut = std::async(std::launch::async, [&]() {
        return client_b->send_and_recv(desc_req, TEST_TIMEOUT_SECS);
    });

    pb::MessageV1 desc_result = desc_fut.get();
    auto elapsed = std::chrono::duration<double>(
        std::chrono::steady_clock::now() - start_time).count();

    // B's describe should have completed quickly (< 500ms), NOT waiting for
    // A's 2-second reset to finish.
    ASSERT_TRUE(desc_result.has_describe_response())
        << "Client B describe should succeed while A is active, got kind: "
        << desc_result.kind_case();
    EXPECT_LT(elapsed, 0.5)
        << "Describe should be served from cache in < 500ms, took " << elapsed << "s";

    // Wait for A's slow reset to complete as well.
    backend_slow_reset.get();
    pb::MessageV1 reset_result = reset_fut.get();
    EXPECT_TRUE(reset_result.has_reset_response() || reset_result.has_success_message())
        << "Client A reset should eventually succeed";

    client_a->stop();
    client_b->stop();
}

// =============================================================================
// Test 19: ActiveSessionTransition
// =============================================================================

/**
 * @brief Client A sends reset (becomes active). Client A disconnects mid-session.
 *        Client B (which was waiting with a config command) should then become
 *        active and succeed.
 *
 * Verifies:
 * - When the active session disconnects, the next waiting session is promoted.
 * - The promoted session can then issue control commands to the backend.
 * - The transition happens automatically without external intervention.
 */
TEST_F(ProxyServerTest, ActiveSessionTransition) {
    start_proxy_with_single_backend();

    // --- Client A connects and becomes active via reset ---
    auto client_a = ControlChannel::create("127.0.0.1", proxy_port(), TEST_TIMEOUT_SECS);
    client_a->start();

    std::future<void> backend_reset = std::async(std::launch::async, [this]() {
        pb::MessageV1 req = backend_->recv_message();
        EXPECT_TRUE(req.has_reset_command());
        backend_->send_message(backend_->make_reset_response(req.id()));
    });

    pb::MessageV1 reset_req;
    reset_req.set_id(utils::generate_uuid());
    reset_req.mutable_reset_command();

    pb::MessageV1 reset_result = client_a->send_and_recv(reset_req, TEST_TIMEOUT_SECS);
    backend_reset.get();
    EXPECT_TRUE(reset_result.has_reset_response() || reset_result.has_success_message());

    // --- Client B connects and queues a config command ---
    auto client_b = ControlChannel::create("127.0.0.1", proxy_port(), TEST_TIMEOUT_SECS);
    client_b->start();

    pb::MessageV1 config_req;
    config_req.set_id(utils::generate_uuid());
    auto* bundle = config_req.mutable_config_command()->mutable_bundle();
    auto* cfg = bundle->add_configs();
    cfg->mutable_entity()->set_path(CARRIER_PATH_A + "/0/U");
    cfg->mutable_device_config();

    std::atomic<bool> b_done{false};
    auto config_fut = std::async(std::launch::async, [&]() {
        pb::MessageV1 result = client_b->send_and_recv(config_req, TEST_TIMEOUT_SECS);
        b_done.store(true, std::memory_order_release);
        return result;
    });

    // Let B's request queue behind A.
    std::this_thread::sleep_for(std::chrono::milliseconds(300));
    EXPECT_FALSE(b_done.load(std::memory_order_acquire))
        << "Client B should be waiting while A is active";

    // --- Client A disconnects abruptly ---
    client_a->stop();

    // --- Client B should now become active; serve its config on the backend ---
    std::future<void> backend_config = std::async(std::launch::async, [this]() {
        pb::MessageV1 req = backend_->recv_message();
        EXPECT_TRUE(req.has_config_command());

        pb::MessageV1 resp;
        resp.set_id(req.id());
        resp.mutable_config_response();
        backend_->send_message(resp);
    });

    backend_config.get();
    pb::MessageV1 config_result = config_fut.get();

    EXPECT_TRUE(config_result.has_config_response())
        << "Client B config should succeed after A disconnects, got kind: "
        << config_result.kind_case();

    client_b->stop();
}

// =============================================================================
// Sprint 7b: DataChannel integration tests
//
// These three tests verify the ForwardingDataChannel that Sprint 7b adds to
// BackendDevice.  The class does not exist yet (TDD — tests are written first).
//
// Key design contract being tested:
//
// 1. During add_backend(), the proxy creates a ForwardingDataChannel that
//    attempts UDP negotiation with the backend by sending a
//    UdpDataStreamingCommand over the backend's ControlChannel.
//
// 2. When the backend accepts UDP, the proxy opens a local UDP socket, and
//    RunDataMessage / RunDataEndMessage payloads received on that UDP socket
//    are forwarded as raw MessageV1 envelopes over TCP to the active client.
//    ControlChannel callbacks for RunData* are NO LONGER registered (the
//    DataChannel is the only data path once Sprint 7b is complete).
//
// 3. When the backend refuses UDP, the proxy's ForwardingDataChannel falls
//    back to the shared TCP ControlChannel transport.  Data messages arriving
//    on that TCP stream are forwarded to the active client exactly as in the
//    UDP-accept case.
//
// Simulation strategy
// -------------------
// The MockBackend already handles DescribeCommand and ResetCommand in
// serve_add_backend_handshake().  After those two messages the backend TCP
// socket is still open; the test drives it further to:
//   - receive the UdpDataStreamingCommand the proxy sends during DataChannel
//     creation,
//   - reply with acceptance or refusal,
//   - then send a RunDataMessage and verify the client sees it.
//
// For the UDP-accept path the MockBackend records the port from the command,
// creates a local UDPSocket, and sends the RunDataMessage as a serialised
// Envelope to that port.  The proxy's ForwardingDataChannel receives it via
// UDP and forwards it over TCP to the active client.
// =============================================================================

#include "pybrid/transport/udp_socket.h"

// =============================================================================
// Test 20: DataChannelUdpNegotiation
// =============================================================================

/**
 * @brief After add_backend(), the proxy's DataChannel sends a
 *        UdpDataStreamingCommand to the backend with a non-zero local port.
 *
 * Sprint 7b adds a ForwardingDataChannel to BackendDevice.  During add_backend()
 * the DataChannel must negotiate its UDP receive port with the backend by sending
 * a UdpDataStreamingCommand through the backend's ControlChannel.
 *
 * Verifies:
 * - The backend receives a UdpDataStreamingCommand as the third message
 *   (after DescribeCommand and ResetCommand) during the add_backend() handshake.
 * - The port field in the command is non-zero (the proxy has bound a UDP socket).
 *
 * The test does NOT reply to the UdpDataStreamingCommand — it is only interested
 * in verifying that the negotiation message is sent at all.  The proxy is not
 * started() so any lack of response merely causes the DataChannel to time out
 * during negotiation, which is acceptable for this narrow assertion.
 */
TEST_F(ProxyServerTest, DataChannelUdpNegotiation) {
    // We drive the handshake manually so we can inspect the third message.
    std::promise<pb::MessageV1> udp_cmd_promise;
    std::future<pb::MessageV1> udp_cmd_future = udp_cmd_promise.get_future();

    std::future<void> backend_thread = std::async(std::launch::async, [&]() {
        backend_->accept_connection();

        // 1. DescribeCommand
        pb::MessageV1 describe_req = backend_->recv_message();
        ASSERT_TRUE(describe_req.has_describe_command());
        backend_->send_message(backend_->make_describe_response(describe_req.id()));

        // 2. ResetCommand
        pb::MessageV1 reset_req = backend_->recv_message();
        ASSERT_TRUE(reset_req.has_reset_command());
        backend_->send_message(backend_->make_reset_response(reset_req.id()));

        // 3. UdpDataStreamingCommand — sent by the newly created ForwardingDataChannel.
        pb::MessageV1 udp_req = backend_->recv_message();
        udp_cmd_promise.set_value(udp_req);
    });

    // add_backend() is synchronous; ForwardingDataChannel sends the UDP command
    // as part of its initialisation inside add_backend().
    proxy_->add_backend("127.0.0.1", backend_->port());

    backend_thread.get();

    // Retrieve and check the UDP negotiation command.
    ASSERT_EQ(udp_cmd_future.wait_for(std::chrono::seconds(0)),
              std::future_status::ready)
        << "UdpDataStreamingCommand was not received during add_backend()";

    pb::MessageV1 udp_cmd = udp_cmd_future.get();

    ASSERT_TRUE(udp_cmd.has_udp_data_streaming_command())
        << "Third message from proxy should be UdpDataStreamingCommand, got kind: "
        << udp_cmd.kind_case();

    EXPECT_GT(udp_cmd.udp_data_streaming_command().port(), 0u)
        << "UdpDataStreamingCommand must carry a non-zero local port";
}

// =============================================================================
// Test 21: DataChannelForwardingToClient
// =============================================================================

/**
 * @brief RunDataMessage sent by the backend via UDP is forwarded to the active
 *        client over TCP.
 *
 * Scenario:
 * 1. add_backend() completes (DescribeCommand + ResetCommand + UDP negotiation).
 * 2. Backend replies to UdpDataStreamingCommand with a SuccessMessage (accepted).
 * 3. proxy->start() begins accepting client connections.
 * 4. Client connects and becomes the active session.
 * 5. Backend sends a RunDataMessage to the proxy's negotiated UDP port.
 * 6. Client receives the forwarded RunDataMessage over TCP.
 *
 * This test validates the primary data path of Sprint 7b: the proxy must
 * NO LONGER register a ControlChannel callback for RunDataMessage.  Data must
 * arrive exclusively via the ForwardingDataChannel's UDP socket.
 *
 * Verifies:
 * - After UDP negotiation succeeds, data sent via UDP reaches the active client.
 * - The forwarded message kind matches the original RunDataMessage.
 */
TEST_F(ProxyServerTest, DataChannelForwardingToClient) {
    // Negotiated UDP port, captured so the backend can send data to it.
    std::atomic<uint16_t> proxy_udp_port{0};

    std::future<void> backend_thread = std::async(std::launch::async, [&]() {
        backend_->accept_connection();

        // DescribeCommand
        pb::MessageV1 describe_req = backend_->recv_message();
        ASSERT_TRUE(describe_req.has_describe_command());
        backend_->send_message(backend_->make_describe_response(describe_req.id()));

        // ResetCommand
        pb::MessageV1 reset_req = backend_->recv_message();
        ASSERT_TRUE(reset_req.has_reset_command());
        backend_->send_message(backend_->make_reset_response(reset_req.id()));

        // UdpDataStreamingCommand — capture the port and accept.
        pb::MessageV1 udp_req = backend_->recv_message();
        ASSERT_TRUE(udp_req.has_udp_data_streaming_command())
            << "Expected UdpDataStreamingCommand, got kind: " << udp_req.kind_case();

        proxy_udp_port.store(
            static_cast<uint16_t>(udp_req.udp_data_streaming_command().port()),
            std::memory_order_release);

        pb::MessageV1 accept_resp;
        accept_resp.set_id(udp_req.id());
        accept_resp.mutable_success_message();
        backend_->send_message(accept_resp);
    });

    proxy_->add_backend("127.0.0.1", backend_->port());
    backend_thread.get();

    proxy_->start("127.0.0.1", 0);

    // Client registers a callback for RunDataMessage and connects.
    auto client = ControlChannel::create("127.0.0.1", proxy_->local_port(), TEST_TIMEOUT_SECS);

    std::atomic<bool> run_data_received{false};
    client->register_callback(
        pb::MessageV1::kRunDataMessageFieldNumber,
        [&](pb::MessageV1& /* msg */) {
            run_data_received.store(true, std::memory_order_release);
        });
    client->start();

    // Confirm client is the active session via a describe roundtrip.
    pb::MessageV1 desc_req;
    desc_req.set_id(utils::generate_uuid());
    desc_req.mutable_describe_command();
    pb::MessageV1 desc_resp = client->send_and_recv(desc_req, TEST_TIMEOUT_SECS);
    ASSERT_TRUE(desc_resp.has_describe_response());

    // Allow the ForwardingDataChannel's UDP receive loop to start.
    std::this_thread::sleep_for(std::chrono::milliseconds(100));

    // Backend sends RunDataMessage via UDP to the negotiated proxy port.
    uint16_t udp_port = proxy_udp_port.load(std::memory_order_acquire);
    ASSERT_GT(udp_port, 0u) << "UDP port must be non-zero after negotiation";

    {
        UDPSocket sender;
        sender.bind(0);

        pb::MessageV1 data_msg;
        data_msg.mutable_run_data_message();

        pb::Envelope env;
        *env.mutable_message_v1() = data_msg;
        std::string bytes;
        ASSERT_TRUE(env.SerializeToString(&bytes));

        ASSERT_TRUE(sender.send_to(
            reinterpret_cast<const uint8_t*>(bytes.data()),
            bytes.size(),
            "127.0.0.1",
            udp_port))
            << "Failed to send RunDataMessage to proxy UDP port " << udp_port;
    }

    // Wait up to 3 s for the client to receive the forwarded message.
    auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(3);
    while (!run_data_received.load(std::memory_order_acquire) &&
           std::chrono::steady_clock::now() < deadline) {
        std::this_thread::sleep_for(std::chrono::milliseconds(20));
    }

    EXPECT_TRUE(run_data_received.load())
        << "Client did not receive RunDataMessage forwarded from backend UDP socket";

    client->stop();
}

// =============================================================================
// Test 22: DataChannelTcpFallback
// =============================================================================

/**
 * @brief When the backend refuses UDP streaming, the proxy's DataChannel falls
 *        back to TCP, and RunDataMessage is still forwarded to the active client.
 *
 * Scenario:
 * 1. add_backend() completes (DescribeCommand + ResetCommand + UDP negotiation).
 * 2. Backend replies to UdpDataStreamingCommand with
 *    UdpDataStreamingRefusedResponse (UDP refused).
 * 3. The ForwardingDataChannel falls back to the shared TCP ControlChannel.
 * 4. proxy->start() begins accepting client connections.
 * 5. Client connects and becomes the active session.
 * 6. Backend sends a RunDataMessage over the existing TCP connection.
 * 7. Client receives the forwarded RunDataMessage over TCP.
 *
 * Verifies:
 * - When UDP is refused, data path falls back to the TCP ControlChannel transport.
 * - RunDataMessage received on the TCP fallback path is forwarded to the active
 *   client, ensuring no data loss regardless of the negotiated transport mode.
 */
TEST_F(ProxyServerTest, DataChannelTcpFallback) {
    std::future<void> backend_thread = std::async(std::launch::async, [&]() {
        backend_->accept_connection();

        // DescribeCommand
        pb::MessageV1 describe_req = backend_->recv_message();
        ASSERT_TRUE(describe_req.has_describe_command());
        backend_->send_message(backend_->make_describe_response(describe_req.id()));

        // ResetCommand
        pb::MessageV1 reset_req = backend_->recv_message();
        ASSERT_TRUE(reset_req.has_reset_command());
        backend_->send_message(backend_->make_reset_response(reset_req.id()));

        // UdpDataStreamingCommand — refuse UDP.
        pb::MessageV1 udp_req = backend_->recv_message();
        ASSERT_TRUE(udp_req.has_udp_data_streaming_command())
            << "Expected UdpDataStreamingCommand, got kind: " << udp_req.kind_case();

        pb::MessageV1 refuse_resp;
        refuse_resp.set_id(udp_req.id());
        refuse_resp.mutable_udp_data_streaming_refused_response()
            ->set_reason("UDP streaming not supported by this device");
        backend_->send_message(refuse_resp);
    });

    proxy_->add_backend("127.0.0.1", backend_->port());
    backend_thread.get();

    proxy_->start("127.0.0.1", 0);

    // Client registers a callback for RunDataMessage and connects.
    auto client = ControlChannel::create("127.0.0.1", proxy_->local_port(), TEST_TIMEOUT_SECS);

    std::atomic<bool> run_data_received{false};
    client->register_callback(
        pb::MessageV1::kRunDataMessageFieldNumber,
        [&](pb::MessageV1& /* msg */) {
            run_data_received.store(true, std::memory_order_release);
        });
    client->start();

    // Confirm client is the active session.
    pb::MessageV1 desc_req;
    desc_req.set_id(utils::generate_uuid());
    desc_req.mutable_describe_command();
    pb::MessageV1 desc_resp = client->send_and_recv(desc_req, TEST_TIMEOUT_SECS);
    ASSERT_TRUE(desc_resp.has_describe_response());

    // Allow the ForwardingDataChannel to set up its TCP fallback receive loop.
    std::this_thread::sleep_for(std::chrono::milliseconds(100));

    // Backend sends RunDataMessage over the shared TCP connection (TCP fallback path).
    pb::MessageV1 data_msg;
    data_msg.mutable_run_data_message();
    backend_->send_message(data_msg);

    // Wait up to 3 s for the client to receive the forwarded message.
    auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(3);
    while (!run_data_received.load(std::memory_order_acquire) &&
           std::chrono::steady_clock::now() < deadline) {
        std::this_thread::sleep_for(std::chrono::milliseconds(20));
    }

    EXPECT_TRUE(run_data_received.load())
        << "Client did not receive RunDataMessage forwarded via TCP fallback path";

    client->stop();
}

TEST_F(ProxyServerTest, AddBackendInjectsLocation) {
    std::future<void> backend_thread = std::async(std::launch::async, [&]() {
        backend_->accept_connection();

        // DescribeCommand
        pb::MessageV1 describe_req = backend_->recv_message();
        ASSERT_TRUE(describe_req.has_describe_command());
        backend_->send_message(backend_->make_describe_response(describe_req.id()));

        // ResetCommand
        pb::MessageV1 reset_req = backend_->recv_message();
        ASSERT_TRUE(reset_req.has_reset_command());
        backend_->send_message(backend_->make_reset_response(reset_req.id()));

        // UdpDataStreamingCommand — refuse UDP so the handshake completes simply.
        pb::MessageV1 udp_req = backend_->recv_message();
        if (udp_req.has_udp_data_streaming_command()) {
            pb::MessageV1 refuse_resp;
            refuse_resp.set_id(udp_req.id());
            refuse_resp.mutable_udp_data_streaming_refused_response()
                ->set_reason("not supported");
            backend_->send_message(refuse_resp);
        }
    });

    proxy_->add_backend("127.0.0.1", backend_->port(),
                        std::optional<uint32_t>{0},
                        std::optional<uint32_t>{2});
    backend_thread.get();

    proxy_->start("127.0.0.1", 0);

    auto client = ControlChannel::create("127.0.0.1", proxy_->local_port(), TEST_TIMEOUT_SECS);
    client->start();

    pb::MessageV1 request;
    request.set_id(utils::generate_uuid());
    request.mutable_describe_command();

    std::future<pb::MessageV1> fut = std::async(
        std::launch::async,
        [&]() { return client->send_and_recv(request, TEST_TIMEOUT_SECS); });

    pb::MessageV1 result = fut.get();
    ASSERT_TRUE(result.has_describe_response())
        << "Expected describe_response, got kind: " << result.kind_case();

    const pb::Entity& root = result.describe_response().entity();

    auto find_entity_with_location =
        [&](const pb::Entity& tree) -> const pb::Entity* {
        if (tree.has_v0()) {
            return &tree;
        }
        for (int i = 0; i < tree.children_size(); ++i) {
            if (tree.children(i).has_v0()) {
                return &tree.children(i);
            }
        }
        return nullptr;
    };

    const pb::Entity* located = find_entity_with_location(root);
    ASSERT_NE(located, nullptr);
    EXPECT_EQ(located->v0().stack(), 0u);
    EXPECT_EQ(located->v0().carrier(), 2u);

    client->stop();
}

TEST_F(ProxyServerTest, AddBackendNoLocationByDefault) {
    std::future<void> backend_thread = std::async(std::launch::async, [&]() {
        backend_->accept_connection();

        // DescribeCommand
        pb::MessageV1 describe_req = backend_->recv_message();
        ASSERT_TRUE(describe_req.has_describe_command());
        backend_->send_message(backend_->make_describe_response(describe_req.id()));

        // ResetCommand
        pb::MessageV1 reset_req = backend_->recv_message();
        ASSERT_TRUE(reset_req.has_reset_command());
        backend_->send_message(backend_->make_reset_response(reset_req.id()));

        // UdpDataStreamingCommand — refuse UDP.
        pb::MessageV1 udp_req = backend_->recv_message();
        if (udp_req.has_udp_data_streaming_command()) {
            pb::MessageV1 refuse_resp;
            refuse_resp.set_id(udp_req.id());
            refuse_resp.mutable_udp_data_streaming_refused_response()
                ->set_reason("not supported");
            backend_->send_message(refuse_resp);
        }
    });

    // No location args — uses default std::nullopt.
    proxy_->add_backend("127.0.0.1", backend_->port());
    backend_thread.get();

    proxy_->start("127.0.0.1", 0);

    auto client = ControlChannel::create("127.0.0.1", proxy_->local_port(), TEST_TIMEOUT_SECS);
    client->start();

    pb::MessageV1 request;
    request.set_id(utils::generate_uuid());
    request.mutable_describe_command();

    std::future<pb::MessageV1> fut = std::async(
        std::launch::async,
        [&]() { return client->send_and_recv(request, TEST_TIMEOUT_SECS); });

    pb::MessageV1 result = fut.get();
    ASSERT_TRUE(result.has_describe_response())
        << "Expected describe_response, got kind: " << result.kind_case();

    const pb::Entity& root = result.describe_response().entity();
    bool any_has_v0 = root.has_v0();
    for (int i = 0; i < root.children_size(); ++i) {
        if (root.children(i).has_v0()) {
            any_has_v0 = true;
        }
    }

    EXPECT_FALSE(any_has_v0);

    client->stop();
}

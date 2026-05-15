/**
 * @file test_control_channel.cpp
 * @brief Unit tests for the ControlChannel class.
 *
 * Uses a real TCP loopback setup: a TCPServer accepts connections,
 * and a TCPTransport created via TCPTransport::from_accepted() simulates
 * the firmware device side of the connection.
 */

#include <gtest/gtest.h>

#include <atomic>
#include <chrono>
#include <future>
#include <regex>
#include <string>
#include <thread>
#include <vector>

#include "pybrid/channel/control_channel.h"
#include "pybrid/proto/main.pb.h"
#include "pybrid/transport/tcp_server.h"
#include "pybrid/transport/tcp_transport.h"
#include "pybrid/utils/uuid.h"

using namespace anabrid::pybrid::native;

class ControlChannelTest : public ::testing::Test {
protected:
    void SetUp() override {
        server_.bind(0);
        server_.start();
    }

    void TearDown() override {
        if (server_transport_) {
            server_transport_->stop();
        }
        server_.stop();
    }

    /** @brief Local port that the server is listening on. */
    uint16_t server_port() const { return server_.local_port(); }

    /**
     * @brief Accept the next inbound connection and create a server-side transport.
     *
     * Blocks until a client connects (or 5 s timeout). Must be called after the
     * ControlChannel::create() call that triggers the connection.
     *
     * @param timeout_secs Maximum time to wait for the connection.
     */
    void accept_one(double timeout_secs = 5.0) {
        AcceptedSocket accepted = server_.accept(timeout_secs);
        ASSERT_TRUE(accepted.is_valid()) << "Server did not accept a connection in time";

        server_transport_ = TCPTransport::from_accepted(std::move(accepted));
        ASSERT_NE(server_transport_, nullptr);
        server_transport_->start();
    }

    /**
     * @brief Read one Envelope from the server-side transport, parse it, and
     *        return the inner MessageV1.
     *
     * @param timeout_secs  Timeout for the recv call.
     * @return The MessageV1 contained in the received Envelope.
     */
    pb::MessageV1 server_recv_message(double timeout_secs = 5.0) {
        EXPECT_NE(server_transport_, nullptr);
        std::vector<uint8_t> buf(65536);
        RecvResult result = server_transport_->recv(buf.data(), buf.size(), timeout_secs);
        EXPECT_EQ(result.status, RecvStatus::Success);
        EXPECT_GT(result.bytes, 0);

        pb::Envelope envelope;
        EXPECT_TRUE(envelope.ParseFromArray(buf.data(), static_cast<int>(result.bytes)));
        EXPECT_TRUE(envelope.has_message_v1());
        return envelope.message_v1();
    }

    /**
     * @brief Send a MessageV1 from the server side wrapped in a pb::Envelope.
     *
     * @param msg The message to send.
     */
    void server_send_message(const pb::MessageV1& msg) {
        ASSERT_NE(server_transport_, nullptr);
        pb::Envelope envelope;
        *envelope.mutable_message_v1() = msg;
        std::string serialized;
        ASSERT_TRUE(envelope.SerializeToString(&serialized));
        ASSERT_TRUE(server_transport_->send(serialized.data(), serialized.size()));
    }

    TCPServer server_;
    std::unique_ptr<TCPTransport> server_transport_;
};

/**
 * @brief ControlChannel::create() connects successfully to a listening server.
 *
 * Verifies:
 * - create() returns a non-null channel.
 * - is_connected() is true immediately after creation.
 * - remote_host() and remote_port() reflect the server address.
 */
TEST_F(ControlChannelTest, CreateAndConnect) {
    auto channel = ControlChannel::create("127.0.0.1", server_port(), 5.0);

    ASSERT_NE(channel, nullptr);
    EXPECT_TRUE(channel->is_connected());
    EXPECT_EQ(channel->remote_host(), "127.0.0.1");
    EXPECT_EQ(channel->remote_port(), server_port());
}

/**
 * @brief ControlChannel::create() throws when no server is listening.
 *
 * Verifies:
 * - create() throws std::runtime_error on connection refused.
 */
TEST(ControlChannelStandaloneTest, CreateConnectionRefused) {
    // Port 1 is privileged and almost certainly not listening.
    EXPECT_THROW(ControlChannel::create("127.0.0.1", 1, 1.0), std::runtime_error);
}

/**
 * @brief start() / stop() lifecycle transitions is_running() correctly.
 *
 * Verifies:
 * - is_running() is false before start().
 * - is_running() is true after start().
 * - is_running() is false after stop().
 * - Calling start() again after stop() is idempotent (no hang or crash).
 */
TEST_F(ControlChannelTest, StartStop) {
    auto channel = ControlChannel::create("127.0.0.1", server_port(), 5.0);

    EXPECT_FALSE(channel->is_running());

    channel->start();
    EXPECT_TRUE(channel->is_running());

    channel->stop();
    EXPECT_FALSE(channel->is_running());

    // A second stop() must be a no-op.
    channel->stop();
    EXPECT_FALSE(channel->is_running());
}

/**
 * @brief send_and_recv() returns the correlated response identified by UUID.
 *
 * Verifies:
 * - An ExtractCommand sent from the client is received on the server.
 * - The server replies with an ExtractResponse carrying the same id.
 * - send_and_recv() returns the correct response module item.
 */
TEST_F(ControlChannelTest, SendAndRecvCorrelation) {
    auto channel = ControlChannel::create("127.0.0.1", server_port(), 5.0);
    accept_one();
    channel->start();

    // Build a request with a known ID.
    const std::string request_id = "test-uuid-1234";
    pb::MessageV1 request;
    request.set_id(request_id);
    auto* cmd = request.mutable_extract_command();
    cmd->set_recursive(true);
    cmd->set_specification(true);

    // Send request from a background thread so we can serve it.
    std::future<pb::MessageV1> response_future = std::async(
        std::launch::async, [&]() { return channel->send_and_recv(request, 5.0); });

    // Server receives the request and checks the id.
    pb::MessageV1 received = server_recv_message(5.0);
    EXPECT_EQ(received.id(), request_id);
    EXPECT_TRUE(received.has_extract_command());

    // Server replies with a correlated ExtractResponse.
    pb::MessageV1 response;
    response.set_id(request_id);
    auto* mod = response.mutable_extract_response()->mutable_module();
    auto* item = mod->add_items();
    item->mutable_entity_specification()->mutable_entity()->set_id("/test-entity");
    server_send_message(response);

    // Caller gets the response.
    pb::MessageV1 result = response_future.get();
    EXPECT_EQ(result.id(), request_id);
    ASSERT_TRUE(result.has_extract_response());
    EXPECT_EQ(result.extract_response().module().items(0).entity_specification().entity().id(), "/test-entity");
}

/**
 * @brief send_and_recv() throws when no reply arrives within the timeout.
 *
 * Verifies:
 * - Sending a request without a server reply causes send_and_recv() to throw
 *   std::runtime_error after the given timeout.
 */
TEST_F(ControlChannelTest, SendAndRecvTimeout) {
    auto channel = ControlChannel::create("127.0.0.1", server_port(), 5.0);
    accept_one();
    channel->start();

    pb::MessageV1 request;
    request.set_id("no-reply-uuid");
    auto* cmd_timeout = request.mutable_extract_command();
    cmd_timeout->set_recursive(true);
    cmd_timeout->set_specification(true);

    // Server receives but intentionally never replies.
    std::thread server_thread([this]() {
        // Drain the request so the client send doesn't block.
        server_recv_message(5.0);
        // Do NOT send a response.
    });

    auto start = std::chrono::steady_clock::now();
    EXPECT_THROW(channel->send_and_recv(request, 0.5), std::runtime_error);
    auto elapsed = std::chrono::steady_clock::now() - start;

    EXPECT_GE(std::chrono::duration<double>(elapsed).count(), 0.4);

    server_thread.join();
}

/**
 * @brief Registered callback is invoked when a notification (empty id) arrives.
 *
 * Verifies:
 * - register_callback() for kRunStateChangeMessageFieldNumber is effective.
 * - Sending a RunStateChangeMessage with empty id from the server triggers
 *   the callback with the correct message payload.
 */
TEST_F(ControlChannelTest, CallbackDispatch) {
    auto channel = ControlChannel::create("127.0.0.1", server_port(), 5.0);
    accept_one();

    std::atomic<bool> callback_called{false};
    pb::RunState received_new_state = pb::NEW;

    channel->register_callback(pb::MessageV1::kRunStateChangeMessageFieldNumber, [&](pb::MessageV1& msg) {
        received_new_state = msg.run_state_change_message().new_();
        callback_called.store(true, std::memory_order_release);
    });

    channel->start();

    // Server sends an unsolicited notification (no id).
    pb::MessageV1 notification;
    // id intentionally left empty — this marks it as a notification.
    notification.mutable_run_state_change_message()->set_new_(pb::OP);
    server_send_message(notification);

    // Wait up to 2 s for the callback to fire.
    auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(2);
    while (!callback_called.load(std::memory_order_acquire) && std::chrono::steady_clock::now() < deadline) {
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }

    EXPECT_TRUE(callback_called.load());
    EXPECT_EQ(received_new_state, pb::OP);
}

/**
 * @brief Unregistering a callback prevents it from being invoked.
 *
 * Verifies:
 * - After unregister_callback(), sending the corresponding notification does
 *   NOT invoke the previously registered callback.
 */
TEST_F(ControlChannelTest, UnregisterCallback) {
    auto channel = ControlChannel::create("127.0.0.1", server_port(), 5.0);
    accept_one();

    std::atomic<int> call_count{0};

    channel->register_callback(pb::MessageV1::kRunStateChangeMessageFieldNumber, [&](pb::MessageV1& /* msg */) {
        call_count.fetch_add(1, std::memory_order_relaxed);
    });

    // Unregister before any message arrives.
    channel->unregister_callback(pb::MessageV1::kRunStateChangeMessageFieldNumber);

    channel->start();

    // Server sends the notification.
    pb::MessageV1 notification;
    notification.mutable_run_state_change_message()->set_new_(pb::IC);
    server_send_message(notification);

    // Give the recv thread time to process the message.
    std::this_thread::sleep_for(std::chrono::milliseconds(300));

    EXPECT_EQ(call_count.load(), 0);
}

/**
 * @brief Calling stop() while a send_and_recv() is waiting breaks the promise.
 *
 * Verifies:
 * - A pending send_and_recv() that has not received a reply throws
 *   std::runtime_error (broken promise) when stop() is called from another
 *   thread.
 */
TEST_F(ControlChannelTest, StopBreaksPendingPromises) {
    auto channel = ControlChannel::create("127.0.0.1", server_port(), 5.0);
    accept_one();
    channel->start();

    pb::MessageV1 request;
    request.set_id("pending-uuid");
    auto* cmd_pending = request.mutable_extract_command();
    cmd_pending->set_recursive(true);
    cmd_pending->set_specification(true);

    // Start send_and_recv in background with a long timeout.
    std::future<pb::MessageV1> fut = std::async(
        std::launch::async, [&]() { return channel->send_and_recv(request, 10.0); });

    // Wait for the server to receive the request (confirms send completed).
    server_recv_message(5.0);

    // Stop the channel from this thread — must break the pending promise.
    std::this_thread::sleep_for(std::chrono::milliseconds(50));
    channel->stop();

    EXPECT_THROW(fut.get(), std::runtime_error);
}

/**
 * @brief on_tcp_response() correctly routes injected raw bytes.
 *
 * Verifies two sub-cases:
 * a) A notification (empty id) injected via on_tcp_response() fires the callback.
 * b) A response (matching id) injected via on_tcp_response() resolves a pending
 *    send_and_recv().
 */
TEST_F(ControlChannelTest, OnTcpResponse) {
    auto channel = ControlChannel::create("127.0.0.1", server_port(), 5.0);
    // No accept_one() needed — we bypass the network entirely here.

    // --- Sub-case a: notification dispatched to callback ---
    std::atomic<bool> notif_received{false};
    channel->register_callback(pb::MessageV1::kExtractResponseFieldNumber, [&](pb::MessageV1& /* msg */) {
        notif_received.store(true, std::memory_order_release);
    });

    // Build a notification envelope (empty id → notification).
    pb::MessageV1 notif_msg;
    auto* notif_mod = notif_msg.mutable_extract_response()->mutable_module();
    auto* notif_item = notif_mod->add_items();
    notif_item->mutable_entity_specification()->mutable_entity()->set_id("/injected");
    pb::Envelope notif_env;
    *notif_env.mutable_message_v1() = notif_msg;
    std::string notif_bytes;
    ASSERT_TRUE(notif_env.SerializeToString(&notif_bytes));

    channel->on_tcp_response(std::vector<uint8_t>(notif_bytes.begin(), notif_bytes.end()));

    EXPECT_TRUE(notif_received.load());

    // --- Sub-case b: correlated response resolves a pending request ---
    channel->start();
    accept_one();

    const std::string req_id = "inject-uuid-9";
    pb::MessageV1 request;
    request.set_id(req_id);
    auto* cmd_inject = request.mutable_extract_command();
    cmd_inject->set_recursive(true);
    cmd_inject->set_specification(true);

    std::future<pb::MessageV1> fut = std::async(
        std::launch::async, [&]() { return channel->send_and_recv(request, 5.0); });

    // Drain the request on the server side so the send completes.
    server_recv_message(5.0);

    // Inject the response directly via on_tcp_response().
    pb::MessageV1 resp_msg;
    resp_msg.set_id(req_id);
    auto* resp_mod = resp_msg.mutable_extract_response()->mutable_module();
    auto* resp_item = resp_mod->add_items();
    resp_item->mutable_entity_specification()->mutable_entity()->set_id("/injected-resp");
    pb::Envelope resp_env;
    *resp_env.mutable_message_v1() = resp_msg;
    std::string resp_bytes;
    ASSERT_TRUE(resp_env.SerializeToString(&resp_bytes));

    channel->on_tcp_response(std::vector<uint8_t>(resp_bytes.begin(), resp_bytes.end()));

    pb::MessageV1 result = fut.get();
    EXPECT_EQ(result.id(), req_id);
    ASSERT_TRUE(result.has_extract_response());
    EXPECT_EQ(result.extract_response().module().items(0).entity_specification().entity().id(), "/injected-resp");
}

namespace {

class BusyReplyScript {
public:
    BusyReplyScript(TCPTransport* transport, int busy_count) : transport_(transport), busy_count_(busy_count) {}

    void run(int turns_to_run) {
        for (int i = 0; i < turns_to_run; ++i) {
            std::vector<uint8_t> buf(65536);
            RecvResult r;
            while (true) {
                if (stop_.load()) return;
                r = transport_->recv(buf.data(), buf.size(), 0.2);
                if (r.status == RecvStatus::Disconnected) return;
                if (r.status == RecvStatus::Success && r.bytes > 0) break;
                // Timeout: loop and re-check stop_.
            }

            pb::Envelope env;
            ASSERT_TRUE(env.ParseFromArray(buf.data(), static_cast<int>(r.bytes)))
                << "BusyReplyScript: failed to parse incoming Envelope";
            if (!env.has_message_v1()) return;
            pb::MessageV1 req = env.message_v1();

            {
                std::lock_guard<std::mutex> lk(mu_);
                observed_ids_.push_back(req.id());
            }

            pb::MessageV1 reply;
            reply.set_id(req.id());
            if (i < busy_count_) {
                reply.mutable_busy_response();
            } else {
                auto* mod = reply.mutable_extract_response()->mutable_module();
                auto* item = mod->add_items();
                item->mutable_entity_specification()->mutable_entity()->set_id("/real-response");
            }

            pb::Envelope out;
            *out.mutable_message_v1() = reply;
            std::string serialized;
            if (!out.SerializeToString(&serialized)) return;
            transport_->send(serialized.data(), serialized.size());
        }
    }

    void stop() { stop_.store(true); }

    std::vector<std::string> observed_ids() {
        std::lock_guard<std::mutex> lk(mu_);
        return observed_ids_;
    }

private:
    TCPTransport* transport_;
    int busy_count_;
    std::atomic<bool> stop_{false};
    std::mutex mu_;
    std::vector<std::string> observed_ids_;
};

/// Build a minimal ExtractCommand MessageV1 with a UUID id.
pb::MessageV1 make_extract_request() {
    pb::MessageV1 msg;
    msg.set_id(anabrid::pybrid::native::utils::generate_uuid());
    auto* cmd = msg.mutable_extract_command();
    cmd->set_recursive(true);
    cmd->set_specification(true);
    return msg;
}

}  // namespace

TEST_F(ControlChannelTest, BusyRetry_NoBusy_ReturnsImmediately) {
    auto channel = ControlChannel::create("127.0.0.1", server_port(), 5.0);
    accept_one();
    channel->start();

    BusyReplyScript script(server_transport_.get(), /*busy_count=*/0);
    std::thread server_thread([&] { script.run(1); });

    pb::MessageV1 request = make_extract_request();
    const std::string original_id = request.id();

    auto t0 = std::chrono::steady_clock::now();
    pb::MessageV1 response = channel->send_and_recv(request, 5.0);
    auto elapsed = std::chrono::steady_clock::now() - t0;

    server_thread.join();

    EXPECT_LT(std::chrono::duration<double>(elapsed).count(), 1.0) << "No-busy case must not wait for the retry tick";
    ASSERT_TRUE(response.has_extract_response());
    EXPECT_EQ(response.id(), original_id);
    EXPECT_EQ(response.extract_response().module().items(0).entity_specification().entity().id(), "/real-response");
}

TEST_F(ControlChannelTest, BusyRetry_SingleBusy_RetriesWithFreshIdAndReturnsFollowUp) {
    // Cap the busy-wait low so a hang surfaces as a timeout in the test runner.
    auto channel = ControlChannel::create("127.0.0.1", server_port(), 5.0, /*max_busy_wait_secs=*/10);
    accept_one();
    channel->start();

    BusyReplyScript script(server_transport_.get(), /*busy_count=*/1);
    std::thread server_thread([&] { script.run(2); });

    pb::MessageV1 request = make_extract_request();
    const std::string original_id = request.id();

    auto t0 = std::chrono::steady_clock::now();
    bool threw = false;
    pb::MessageV1 response;
    try {
        response = channel->send_and_recv(request, 15.0);
    } catch (const std::runtime_error&) {
        threw = true;
    }
    auto elapsed_secs = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();

    script.stop();
    channel->stop();
    if (server_thread.joinable()) server_thread.join();

    ASSERT_FALSE(threw) << "send_and_recv must succeed after single retry";

    // Expected: ~2 s poll interval; allow generous upper bound for CI.
    EXPECT_GE(elapsed_secs, 1.5);
    EXPECT_LT(elapsed_secs, 4.0);

    auto ids = script.observed_ids();
    ASSERT_EQ(ids.size(), 2u);
    EXPECT_EQ(ids[0], original_id);
    EXPECT_NE(ids[1], original_id) << "Retry must carry a regenerated MessageV1 id";
    EXPECT_FALSE(ids[1].empty());

    ASSERT_TRUE(response.has_extract_response());
    EXPECT_FALSE(response.has_busy_response());
    EXPECT_EQ(response.extract_response().module().items(0).entity_specification().entity().id(), "/real-response");
}

TEST_F(ControlChannelTest, BusyRetry_ExceedsMaxWait_Throws) {
    auto channel = ControlChannel::create("127.0.0.1", server_port(), 5.0, /*max_busy_wait_secs=*/2);
    accept_one();
    channel->start();

    // INT_MAX-ish busy replies so the cap, not the script, ends the test.
    BusyReplyScript script(server_transport_.get(), /*busy_count=*/1000);
    std::thread server_thread([&] { script.run(1000); });

    pb::MessageV1 request = make_extract_request();

    auto t0 = std::chrono::steady_clock::now();
    bool threw = false;
    std::string error_msg;
    try {
        channel->send_and_recv(request, 60.0);
    } catch (const std::runtime_error& e) {
        threw = true;
        error_msg = e.what();
    }
    auto elapsed_secs = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();

    script.stop();
    // Stopping the channel releases the server-side recv loop.
    channel->stop();
    if (server_thread.joinable()) server_thread.join();

    ASSERT_TRUE(threw) << "Expected std::runtime_error from busy cap";
    EXPECT_GE(elapsed_secs, 1.5);
    EXPECT_LT(elapsed_secs, 6.0);

    EXPECT_NE(error_msg.find("busy"), std::string::npos) << "Error message must mention busy state: " << error_msg;
    // Must mention both an elapsed value (e.g. "2.0s" or "2.1s") and the
    // configured cap ("max wait of 2s"). The elapsed value must be non-zero.
    EXPECT_NE(error_msg.find("max wait of 2s"), std::string::npos)
        << "Error message must mention the configured cap: " << error_msg;
    EXPECT_EQ(error_msg.find("busy for 0"), std::string::npos)
        << "Elapsed must be non-zero when the cap actually tripped: " << error_msg;
}

TEST_F(ControlChannelTest, BusyRetry_MaxWaitIsPerInstance) {
    // Default is 60 via the public getter.
    auto default_channel = ControlChannel::create("127.0.0.1", server_port(), 5.0);
    accept_one();
    EXPECT_EQ(default_channel->max_busy_wait_secs(), 60u);
    default_channel->stop();

    // Need a second server for the short-capped channel.
    TCPServer short_server;
    short_server.bind(0);
    short_server.start();

    auto short_channel = ControlChannel::create("127.0.0.1", short_server.local_port(), 5.0, /*max_busy_wait_secs=*/1);
    AcceptedSocket accepted = short_server.accept(5.0);
    ASSERT_TRUE(accepted.is_valid());
    auto short_server_transport = TCPTransport::from_accepted(std::move(accepted));
    short_server_transport->start();

    short_channel->start();

    BusyReplyScript script(short_server_transport.get(), /*busy_count=*/1000);
    std::thread t([&] { script.run(1000); });

    auto t0 = std::chrono::steady_clock::now();
    EXPECT_THROW(short_channel->send_and_recv(make_extract_request(), 60.0), std::runtime_error);
    auto elapsed = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();

    EXPECT_LT(elapsed, 4.0) << "1-s cap must fire faster than default 60 s";

    script.stop();
    short_channel->stop();
    if (t.joinable()) t.join();
    short_server_transport->stop();
    short_server.stop();
}

TEST_F(ControlChannelTest, BusyRetry_CancelUnblocksPromptly) {
    auto channel = ControlChannel::create("127.0.0.1", server_port(), 5.0, /*max_busy_wait_secs=*/30);
    accept_one();
    channel->start();

    BusyReplyScript script(server_transport_.get(), /*busy_count=*/1000);
    std::thread server_thread([&] { script.run(1000); });

    // Cancel ~100 ms in — well before the 2 s busy poll interval elapses.
    std::thread canceller([&] {
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
        channel->cancel_send_and_recv();
    });

    pb::MessageV1 request = make_extract_request();

    auto t0 = std::chrono::steady_clock::now();
    bool threw = false;
    std::string error_msg;
    try {
        channel->send_and_recv(request, 60.0);
    } catch (const std::runtime_error& e) {
        threw = true;
        error_msg = e.what();
    }
    auto elapsed = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();

    canceller.join();
    script.stop();
    channel->stop();
    if (server_thread.joinable()) server_thread.join();

    ASSERT_TRUE(threw) << "Expected std::runtime_error from cancel";
    EXPECT_LT(elapsed, 2.0) << "Cancel must unblock before the next busy-poll tick";

    EXPECT_NE(error_msg.find("cancelled"), std::string::npos)
        << "Error message must mention cancellation: " << error_msg;
}

// Every command wrapper routes through send_and_recv(), so one representative
// invocation per wrapper is enough to catch a wrapper that bypasses the retry.
enum class CommandKind {
    Extract,
    SetModule,
    Reset,
    Authenticate,
    StartRun,
    RawSendAndRecv,
};

class BusyRetryWrapperTest : public ControlChannelTest, public ::testing::WithParamInterface<CommandKind> {};

TEST_P(BusyRetryWrapperTest, EveryWrapperInheritsRetry) {
    auto channel = ControlChannel::create("127.0.0.1", server_port(), 5.0, /*max_busy_wait_secs=*/15);
    accept_one();
    channel->start();

    // Two busy replies, then the real response.
    BusyReplyScript script(server_transport_.get(), /*busy_count=*/2);
    std::thread server_thread([&] { script.run(3); });

    auto invoke = [&](CommandKind kind) {
        switch (kind) {
            case CommandKind::Extract: channel->extract("/", true, true, false, false, 15.0); break;
            case CommandKind::SetModule: {
                pb::Module m;
                channel->set_module(m, 15.0);
                break;
            }
            case CommandKind::Reset: channel->reset(true, true, 15.0); break;
            case CommandKind::Authenticate: channel->authenticate("token", 15.0); break;
            case CommandKind::StartRun: {
                pb::StartRunCommand run;
                channel->start_run_request(run, 15.0);
                break;
            }
            case CommandKind::RawSendAndRecv: channel->send_and_recv(make_extract_request(), 15.0); break;
        }
    };

    // Must complete without throwing — the wrapper has to keep retrying past
    // the two busy replies until the real response arrives.
    auto t0 = std::chrono::steady_clock::now();
    bool threw = false;
    try {
        invoke(GetParam());
    } catch (...) {
        threw = true;
    }
    auto elapsed = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();

    script.stop();
    channel->stop();
    if (server_thread.joinable()) server_thread.join();

    ASSERT_FALSE(threw) << "Wrapper must complete successfully after retries";

    // ~4 s (two 2-s poll intervals) expected, allow up to 7 s. Lower bound
    // loosened to 2.5 s so weak CI runners (notably macOS) don't flake.
    EXPECT_GE(elapsed, 2.5);
    EXPECT_LT(elapsed, 7.0);

    auto ids = script.observed_ids();
    ASSERT_EQ(ids.size(), 3u);
    EXPECT_NE(ids[0], ids[1]);
    EXPECT_NE(ids[1], ids[2]);
}

INSTANTIATE_TEST_SUITE_P(
    AllWrappers,
    BusyRetryWrapperTest,
    ::testing::Values(
        CommandKind::Extract,
        CommandKind::SetModule,
        CommandKind::Reset,
        CommandKind::Authenticate,
        CommandKind::StartRun,
        CommandKind::RawSendAndRecv));

/**
 * @brief utils::generate_uuid() produces valid UUID v4 strings.
 *
 * Verifies:
 * - The output is non-empty.
 * - The output matches the UUID v4 regex:
 *     xxxxxxxx-xxxx-4xxx-[89ab]xxx-xxxxxxxxxxxx
 * - Two consecutive calls produce different UUIDs.
 */
TEST(UtilsTest, GenerateUuidFormat) {
    using anabrid::pybrid::native::utils::generate_uuid;

    std::string uuid1 = generate_uuid();
    std::string uuid2 = generate_uuid();

    EXPECT_FALSE(uuid1.empty());
    EXPECT_FALSE(uuid2.empty());
    EXPECT_NE(uuid1, uuid2);

    // UUID v4 pattern: xxxxxxxx-xxxx-4xxx-[89ab]xxx-xxxxxxxxxxxx.
    static const std::regex uuid_v4_re(
        R"([0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})", std::regex_constants::icase);
    EXPECT_TRUE(std::regex_match(uuid1, uuid_v4_re)) << "Generated UUID does not match v4 format: " << uuid1;
    EXPECT_TRUE(std::regex_match(uuid2, uuid_v4_re)) << "Generated UUID does not match v4 format: " << uuid2;
}

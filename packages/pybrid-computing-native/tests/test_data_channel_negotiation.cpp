/**
 * @file test_data_channel_negotiation.cpp
 * @brief Unit tests for DataChannel UDP negotiation (Sprint 7a, TDD).
 *
 * These tests verify the interaction between DataChannel and ControlChannel
 * during UDP negotiation: the device is told where to send UDP data via a
 * UdpDataStreamingCommand sent over the control channel, and it replies with
 * either a success (UDP accepted) or a UdpDataStreamingRefusedResponse
 * (UDP refused, fall back to TCP).
 *
 * ## New API under test (does NOT exist yet — tests are expected to FAIL):
 *
 *   DataChannel::set_control_channel(ControlChannel* cc)
 *       Store a non-owning ControlChannel reference for UDP negotiation.
 *
 *   bool DataChannel::negotiate_udp(uint16_t local_port)
 *       Send UdpDataStreamingCommand through the control channel and block
 *       for the response. Returns true on success, false if refused.
 *       Throws std::runtime_error if no response arrives within the timeout.
 *
 * ## Modified start() behaviour (also under test):
 *
 *   After binding the UDP socket, if m_control_channel is set and no explicit
 *   UDP endpoint was pre-configured via set_udp_endpoint(), call
 *   negotiate_udp(bound_port):
 *     - If negotiation returns true  → proceed with UDP receive loop.
 *     - If negotiation returns false → fall back to TCP (is_using_tcp_fallback()).
 *     - If negotiation throws        → report error via on_error() callback.
 *
 * ## Test fixture
 *
 * Each test spins up a real loopback TCPServer that acts as the "device" side
 * of both the control channel and (in the fallback case) the data channel TCP
 * stream. A real ControlChannel is created connecting to that server, and a
 * SampleDecodingDataChannel has its control channel set to that ControlChannel.
 *
 * Tests drive the "device" side by calling server_recv_message() /
 * server_send_message() — identical in style to test_control_channel.cpp.
 */

#include <gtest/gtest.h>

#include <atomic>
#include <chrono>
#include <future>
#include <string>
#include <thread>
#include <vector>

#include "pybrid/channel/control_channel.h"
#include "pybrid/channel/data_channel.h"
#include "pybrid/channel/sample_decoding_data_channel.h"
#include "pybrid/proto/main.pb.h"
#include "pybrid/transport/tcp_server.h"
#include "pybrid/transport/tcp_transport.h"

using namespace anabrid::pybrid::native;

// =============================================================================
// Test fixture
// =============================================================================

/**
 * @brief Test fixture providing a loopback TCP server + accepted server-side
 *        transport, mirroring the style used by ControlChannelTest.
 *
 * Call accept_one() after the ControlChannel has connected to obtain the
 * server-side transport. Use server_recv_message() / server_send_message()
 * to drive the "device" side of the protocol.
 */
class DataChannelNegotiationTest : public ::testing::Test {
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

    /** @brief Local port that the mock device server is listening on. */
    uint16_t server_port() const { return server_.local_port(); }

    /**
     * @brief Accept the next inbound connection as a server-side transport.
     *
     * Blocks until a client connects or 5 s elapses. Must be called after
     * ControlChannel::create() to capture the client's TCP connection.
     */
    void accept_one(double timeout_secs = 5.0) {
        AcceptedSocket accepted = server_.accept(timeout_secs);
        ASSERT_TRUE(accepted.is_valid())
            << "Mock device server did not accept a connection in time";

        server_transport_ = TCPTransport::from_accepted(std::move(accepted));
        ASSERT_NE(server_transport_, nullptr);
        server_transport_->start();
    }

    /**
     * @brief Read one Envelope from the server-side transport, parse it, and
     *        return the inner MessageV1.
     *
     * @param timeout_secs  Maximum time to wait for bytes.
     * @return The MessageV1 extracted from the received Envelope.
     */
    pb::MessageV1 server_recv_message(double timeout_secs = 5.0) {
        EXPECT_NE(server_transport_, nullptr);
        std::vector<uint8_t> buf(65536);
        RecvResult result = server_transport_->recv(buf.data(), buf.size(), timeout_secs);
        EXPECT_EQ(result.status, RecvStatus::Success);
        EXPECT_GT(result.bytes, 0u);

        pb::Envelope envelope;
        EXPECT_TRUE(envelope.ParseFromArray(buf.data(), static_cast<int>(result.bytes)));
        EXPECT_TRUE(envelope.has_message_v1());
        return envelope.message_v1();
    }

    /**
     * @brief Send a MessageV1 from the server side wrapped in a pb::Envelope.
     *
     * @param msg The message to send back to the DataChannel / ControlChannel.
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

// =============================================================================
// Test 1: NegotiateUdpAccepted
// =============================================================================

/**
 * @brief UDP negotiation succeeds: device responds with a SuccessMessage.
 *
 * Scenario:
 *   1. The DataChannel's start() sends a UdpDataStreamingCommand over the
 *      control channel's TCP connection (the "device" server receives it).
 *   2. The mock device validates the command contains a non-zero port.
 *   3. The mock device replies with a SuccessMessage bearing the same UUID.
 *   4. After start() returns, DataChannel must be running in UDP mode
 *      (is_using_tcp_fallback() == false).
 *
 * The SampleDecodingDataChannel is given:
 *   - A UDP bind port of 0 (ephemeral) — so start() must negotiate.
 *   - No explicit UDP endpoint (set_udp_endpoint() NOT called).
 *   - A ControlChannel reference set via set_control_channel().
 *
 * Verifies:
 *   - set_control_channel() is accepted without error.
 *   - start() sends exactly one UdpDataStreamingCommand to the device.
 *   - The command's port field is non-zero (the bound ephemeral port).
 *   - After a SuccessMessage reply, is_using_tcp_fallback() returns false.
 *   - is_running() returns true after start().
 */
TEST_F(DataChannelNegotiationTest, NegotiateUdpAccepted) {
    // Create the control channel (this connects to our mock device server).
    auto ctrl = ControlChannel::create("127.0.0.1", server_port(), 5.0);
    ASSERT_NE(ctrl, nullptr);

    // Accept the TCP connection on the server side.
    accept_one();

    // Start the ControlChannel recv loop so it can process the negotiation reply.
    ctrl->start();

    // Build and configure the data channel.
    SampleDecodingDataChannel data_channel;
    data_channel.set_udp_bind_port(0);  // ephemeral — forces negotiation
    data_channel.set_control_channel(ctrl.get());

    // Launch start() on a background thread so we can service the negotiation
    // from the "device" side concurrently.
    std::future<void> start_future = std::async(std::launch::async, [&]() {
        data_channel.start();
    });

    // --- Device side: receive the UdpDataStreamingCommand ---
    pb::MessageV1 negotiation_request = server_recv_message(5.0);
    ASSERT_TRUE(negotiation_request.has_udp_data_streaming_command())
        << "Expected UdpDataStreamingCommand on the control TCP channel";

    const uint32_t negotiated_port =
        negotiation_request.udp_data_streaming_command().port();
    EXPECT_GT(negotiated_port, 0u)
        << "UdpDataStreamingCommand must carry a non-zero local port";

    // Device accepts: reply with SuccessMessage, correlated by UUID.
    pb::MessageV1 response;
    response.set_id(negotiation_request.id());
    response.mutable_success_message();  // sets kind = SuccessMessage
    server_send_message(response);

    // Wait for start() to complete (it should unblock after receiving the reply).
    start_future.get();

    // Assertions: UDP mode is active, no fallback.
    EXPECT_TRUE(data_channel.is_running());
    EXPECT_FALSE(data_channel.is_using_tcp_fallback())
        << "DataChannel must be in UDP mode after successful negotiation";

    data_channel.stop();
}

// =============================================================================
// Test 2: NegotiateUdpRefused
// =============================================================================

/**
 * @brief UDP negotiation is refused: device responds with
 *        UdpDataStreamingRefusedResponse, DataChannel falls back to TCP.
 *
 * Scenario:
 *   1. start() sends a UdpDataStreamingCommand over the control channel.
 *   2. The mock device replies with UdpDataStreamingRefusedResponse.
 *   3. DataChannel must fall back to TCP: is_using_tcp_fallback() == true.
 *   4. The fallback TCP transport must be the control channel's transport
 *      (set via set_tcp_transport() before start(), or automatically wired
 *      when negotiate_udp() returns false).
 *
 * For the fallback to work, the DataChannel must share the control channel's
 * TCP transport (ctrl->transport()) so it can receive data messages on the
 * same connection.
 *
 * Verifies:
 *   - UdpDataStreamingRefusedResponse causes is_using_tcp_fallback() == true.
 *   - is_running() returns true after start() (channel still operational).
 *   - The data channel can be stopped cleanly.
 */
TEST_F(DataChannelNegotiationTest, NegotiateUdpRefused) {
    // Create the control channel and connect to the mock device.
    auto ctrl = ControlChannel::create("127.0.0.1", server_port(), 5.0);
    ASSERT_NE(ctrl, nullptr);

    accept_one();
    ctrl->start();

    // Configure the data channel for negotiation.
    SampleDecodingDataChannel data_channel;
    data_channel.set_udp_bind_port(0);
    data_channel.set_control_channel(ctrl.get());

    // The DataChannel must share the ControlChannel's TCP transport so that
    // after refused UDP, data messages can arrive over the shared TCP stream.
    // According to the design, when negotiate_udp() returns false, the
    // DataChannel internally calls set_tcp_transport(cc->transport()).
    // We also pre-wire the control response callback so that control responses
    // that arrive on the shared TCP stream are routed back to the ControlChannel.
    data_channel.set_control_response_callback(
        [&ctrl](std::vector<uint8_t> data) {
            ctrl->on_tcp_response(std::move(data));
        });

    // Run start() in background to allow concurrent server-side handling.
    std::future<void> start_future = std::async(std::launch::async, [&]() {
        data_channel.start();
    });

    // --- Device side: receive the UdpDataStreamingCommand and refuse it ---
    pb::MessageV1 negotiation_request = server_recv_message(5.0);
    ASSERT_TRUE(negotiation_request.has_udp_data_streaming_command())
        << "Expected UdpDataStreamingCommand from DataChannel";

    // Reply with UdpDataStreamingRefusedResponse, correlated by UUID.
    pb::MessageV1 refused_response;
    refused_response.set_id(negotiation_request.id());
    refused_response.mutable_udp_data_streaming_refused_response();
    server_send_message(refused_response);

    // Wait for start() to finish processing the refusal.
    start_future.get();

    // Assertions: DataChannel must have fallen back to TCP.
    EXPECT_TRUE(data_channel.is_running());
    EXPECT_TRUE(data_channel.is_using_tcp_fallback())
        << "DataChannel must switch to TCP fallback after UDP is refused";

    data_channel.stop();
}

// =============================================================================
// Test 3: NegotiateUdpTimeout
// =============================================================================

/**
 * @brief UDP negotiation times out: device accepts the TCP connection but
 *        never replies to the UdpDataStreamingCommand.
 *
 * Scenario:
 *   1. start() sends a UdpDataStreamingCommand over the control channel.
 *   2. The mock device drains the message from the TCP buffer but does NOT
 *      send a response (simulating a firmware that hangs or drops the message).
 *   3. After the negotiation timeout (configured to a short value — 1 second),
 *      DataChannel must invoke the on_error() callback with a non-empty
 *      error message.
 *
 * Important implementation note: the test configures a short negotiation
 * timeout. The DataChannel::negotiate_udp() implementation is expected to
 * throw std::runtime_error (which it gets from ControlChannel::send_and_recv()
 * when the timeout expires). DataChannel::start() must catch this and route
 * it to the on_error() callback.
 *
 * Verifies:
 *   - on_error() callback fires with a non-empty message.
 *   - The elapsed time is at least ~1 second (real timeout occurred, not an
 *     immediate failure caused by a connection error).
 *   - The channel does not hang indefinitely in start().
 */
TEST_F(DataChannelNegotiationTest, NegotiateUdpTimeout) {
    // Create the control channel connected to the mock device.
    auto ctrl = ControlChannel::create("127.0.0.1", server_port(), 5.0);
    ASSERT_NE(ctrl, nullptr);

    accept_one();
    ctrl->start();

    // Configure the data channel with a very short negotiation timeout so the
    // test does not take long. The timeout is passed via the ControlChannel's
    // send_and_recv() timeout — the data channel must forward the timeout
    // parameter to negotiate_udp(). We test that the negotiation timeout fires
    // correctly by observing wall-clock elapsed time.
    SampleDecodingDataChannel data_channel;
    data_channel.set_udp_bind_port(0);
    data_channel.set_control_channel(ctrl.get());

    // The negotiation timeout must be configurable. Sprint 7a exposes it via
    // set_negotiation_timeout(double secs) or as a constructor parameter.
    // We use 1 second to keep the test fast while still being a real timeout.
    data_channel.set_negotiation_timeout(1.0);

    // Register the error callback before start().
    std::atomic<bool> error_received{false};
    std::string error_message;
    data_channel.on_error([&](const std::string& msg) {
        error_message = msg;
        error_received.store(true, std::memory_order_release);
    });

    // Run start() in the background so we can time it from this thread.
    auto wall_start = std::chrono::steady_clock::now();
    std::future<void> start_future = std::async(std::launch::async, [&]() {
        data_channel.start();
    });

    // --- Device side: drain the command but never reply ---
    pb::MessageV1 negotiation_request = server_recv_message(5.0);
    ASSERT_TRUE(negotiation_request.has_udp_data_streaming_command())
        << "Expected UdpDataStreamingCommand from DataChannel";
    // Intentionally do NOT call server_send_message() — simulate timeout.

    // start() must return (unblock) after the negotiation timeout fires.
    start_future.get();

    auto elapsed = std::chrono::steady_clock::now() - wall_start;
    double elapsed_secs = std::chrono::duration<double>(elapsed).count();

    // The timeout was set to 1 second; allow up to 5 s for test machinery.
    EXPECT_GE(elapsed_secs, 0.9)
        << "start() returned too quickly — timeout may not have fired";
    EXPECT_LT(elapsed_secs, 5.0)
        << "start() took too long — possible hang in negotiate_udp()";

    // The on_error() callback must have been invoked.
    EXPECT_TRUE(error_received.load(std::memory_order_acquire))
        << "on_error() must be called when UDP negotiation times out";
    EXPECT_FALSE(error_message.empty())
        << "Error message must be non-empty on negotiation timeout";

    // Without require_udp, the channel falls back to TCP after a timeout —
    // it stays running in TCP fallback mode.
    EXPECT_TRUE(data_channel.is_running())
        << "DataChannel must be running in TCP fallback after negotiation timeout";
    EXPECT_TRUE(data_channel.is_using_tcp_fallback())
        << "DataChannel must have fallen back to TCP after negotiation timeout";

    data_channel.stop();
}

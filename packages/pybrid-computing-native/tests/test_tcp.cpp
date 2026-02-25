#include <gtest/gtest.h>

#include <atomic>
#include <chrono>
#include <cstring>
#include <random>
#include <thread>
#include <vector>

#include "pybrid/transport/tcp_transport.h"
#include "pybrid/transport/udp_socket.h"
#include "pybrid/varint.h"

using namespace anabrid::pybrid::native;

// ============================================================================
// Varint Tests
// ============================================================================

class VarintTest : public ::testing::Test {};

TEST_F(VarintTest, EncodeSingleByte) {
    uint8_t buf[MAX_VARINT_SIZE];

    // Values 0-127 should encode to single byte
    EXPECT_EQ(encode_varint(0, buf), 1u);
    EXPECT_EQ(buf[0], 0x00);

    EXPECT_EQ(encode_varint(1, buf), 1u);
    EXPECT_EQ(buf[0], 0x01);

    EXPECT_EQ(encode_varint(127, buf), 1u);
    EXPECT_EQ(buf[0], 0x7F);
}

TEST_F(VarintTest, EncodeTwoBytes) {
    uint8_t buf[MAX_VARINT_SIZE];

    // 128 requires 2 bytes
    EXPECT_EQ(encode_varint(128, buf), 2u);
    EXPECT_EQ(buf[0], 0x80);
    EXPECT_EQ(buf[1], 0x01);

    // 300 = 0x12C = 0b100101100
    // Low 7 bits: 0101100 = 0x2C, with continuation bit: 0xAC
    // Next 7 bits: 0000010 = 0x02
    EXPECT_EQ(encode_varint(300, buf), 2u);
    EXPECT_EQ(buf[0], 0xAC);
    EXPECT_EQ(buf[1], 0x02);
}

TEST_F(VarintTest, EncodeMultipleBytes) {
    uint8_t buf[MAX_VARINT_SIZE];

    // Large value
    EXPECT_EQ(encode_varint(0xFFFFFFFF, buf), 5u);

    // Maximum uint64
    EXPECT_EQ(encode_varint(0xFFFFFFFFFFFFFFFF, buf), 10u);
}

TEST_F(VarintTest, DecodeRoundTrip) {
    uint8_t buf[MAX_VARINT_SIZE];

    std::vector<uint64_t> test_values = {0,      1,        127,  128,
                                         255,    256,      1000, 0xFFFF,
                                         0xFFFFFFFF, 0xFFFFFFFFFFFFFFFF};

    for (uint64_t expected : test_values) {
        size_t encoded_len = encode_varint(expected, buf);
        EXPECT_GT(encoded_len, 0u);

        uint64_t decoded;
        size_t decoded_len = decode_varint(buf, encoded_len, decoded);

        EXPECT_EQ(decoded_len, encoded_len) << "Value: " << expected;
        EXPECT_EQ(decoded, expected) << "Value: " << expected;
    }
}

TEST_F(VarintTest, DecodeIncomplete) {
    uint8_t buf[] = {0x80, 0x80};  // Continuation bits set but no terminator

    uint64_t out;
    EXPECT_EQ(decode_varint(buf, 2, out), 0u);  // Incomplete
}

TEST_F(VarintTest, DecodeFromLargerBuffer) {
    uint8_t buf[20];
    size_t encoded_len = encode_varint(300, buf);

    // Fill rest with garbage
    std::memset(buf + encoded_len, 0xFF, sizeof(buf) - encoded_len);

    uint64_t decoded;
    size_t decoded_len = decode_varint(buf, sizeof(buf), decoded);

    EXPECT_EQ(decoded_len, encoded_len);
    EXPECT_EQ(decoded, 300u);
}

TEST_F(VarintTest, VarintSize) {
    EXPECT_EQ(varint_size(0), 1u);
    EXPECT_EQ(varint_size(127), 1u);
    EXPECT_EQ(varint_size(128), 2u);
    EXPECT_EQ(varint_size(16383), 2u);
    EXPECT_EQ(varint_size(16384), 3u);
}

// ============================================================================
// TCP Transport Tests (using loopback)
// ============================================================================

class TCPTransportTest : public ::testing::Test {
protected:
    void SetUp() override {
        // Create a simple echo server for testing
        server_io_ = std::make_unique<asio::io_context>();
        server_acceptor_ = std::make_unique<asio::ip::tcp::acceptor>(
            *server_io_,
            asio::ip::tcp::endpoint(asio::ip::tcp::v4(), 0));

        server_port_ = server_acceptor_->local_endpoint().port();
        server_running_ = true;

        server_thread_ = std::thread([this]() { run_echo_server(); });
    }

    void TearDown() override {
        server_running_ = false;
        server_io_->stop();
        if (server_thread_.joinable()) {
            server_thread_.join();
        }
    }

    uint16_t server_port() const { return server_port_; }

private:
    void run_echo_server() {
        try {
            server_acceptor_->async_accept([this](const asio::error_code& ec,
                                                   asio::ip::tcp::socket socket) {
                if (!ec && server_running_) {
                    handle_client(std::move(socket));
                }
            });
            server_io_->run();
        } catch (...) {
            // Server error, ignore in tests
        }
    }

    void handle_client(asio::ip::tcp::socket socket) {
        auto client = std::make_shared<asio::ip::tcp::socket>(std::move(socket));
        auto buffer = std::make_shared<std::vector<uint8_t>>(65536);

        do_read(client, buffer);
    }

    void do_read(std::shared_ptr<asio::ip::tcp::socket> socket,
                 std::shared_ptr<std::vector<uint8_t>> buffer) {
        socket->async_read_some(
            asio::buffer(*buffer),
            [this, socket, buffer](const asio::error_code& ec, size_t bytes) {
                if (!ec && server_running_) {
                    // Echo back what we received
                    asio::async_write(
                        *socket, asio::buffer(buffer->data(), bytes),
                        [this, socket, buffer](const asio::error_code& ec2,
                                               size_t /*bytes2*/) {
                            if (!ec2 && server_running_) {
                                do_read(socket, buffer);
                            }
                        });
                }
            });
    }

    std::unique_ptr<asio::io_context> server_io_;
    std::unique_ptr<asio::ip::tcp::acceptor> server_acceptor_;
    std::thread server_thread_;
    uint16_t server_port_{0};
    std::atomic<bool> server_running_{false};
};

TEST_F(TCPTransportTest, ConnectAndDisconnect) {
    TCPTransport transport;
    transport.start();

    EXPECT_FALSE(transport.is_connected());

    bool connected = transport.connect("127.0.0.1", server_port(), 5.0);
    EXPECT_TRUE(connected);
    EXPECT_TRUE(transport.is_connected());

    transport.disconnect();
    EXPECT_FALSE(transport.is_connected());

    transport.stop();
}

TEST_F(TCPTransportTest, ConnectFailure) {
    TCPTransport transport;
    transport.start();

    // Try to connect to a port that won't exist on localhost
    // This should fail with connection refused (fast) or timeout
    bool connected = transport.connect("127.0.0.1", 1, 1.0);

    // Connection should fail (port 1 is privileged and likely not listening)
    EXPECT_FALSE(connected);

    transport.stop();
}

TEST_F(TCPTransportTest, SendReceiveSimple) {
    TCPTransport transport;
    transport.start();

    ASSERT_TRUE(transport.connect("127.0.0.1", server_port(), 5.0));

    // Send a message
    const char* msg = "Hello, TCP!";
    EXPECT_TRUE(transport.send(msg, std::strlen(msg)));

    // Wait for echo
    std::this_thread::sleep_for(std::chrono::milliseconds(100));

    // Receive the echo (into buffer)
    std::vector<uint8_t> recv_buf(65536);
    auto result = transport.recv(recv_buf.data(), recv_buf.size(), 1.0);

    EXPECT_EQ(result.status, RecvStatus::Success);
    EXPECT_EQ(result.bytes, static_cast<ssize_t>(std::strlen(msg)));
    EXPECT_EQ(std::memcmp(recv_buf.data(), msg, std::strlen(msg)), 0);

    transport.stop();
}

TEST_F(TCPTransportTest, SendReceiveMultiple) {
    TCPTransport transport;
    transport.start();

    ASSERT_TRUE(transport.connect("127.0.0.1", server_port(), 5.0));

    const int NUM_MESSAGES = 10;

    // Send multiple messages
    for (int i = 0; i < NUM_MESSAGES; ++i) {
        std::string msg = "Message " + std::to_string(i);
        EXPECT_TRUE(transport.send(msg.data(), msg.size()));
    }

    // Wait for processing
    EXPECT_TRUE(transport.drain(2.0));

    // Receive all echoes
    std::vector<uint8_t> recv_buf(65536);
    int received_count = 0;
    for (int i = 0; i < NUM_MESSAGES; ++i) {
        auto result = transport.recv(recv_buf.data(), recv_buf.size(), 1.0);
        if (result.status == RecvStatus::Success) {
            ++received_count;
        }
    }

    EXPECT_EQ(received_count, NUM_MESSAGES);

    transport.stop();
}

TEST_F(TCPTransportTest, RecvTimeout) {
    TCPTransport transport;
    transport.start();

    ASSERT_TRUE(transport.connect("127.0.0.1", server_port(), 5.0));

    // Don't send anything, just try to receive with timeout
    std::vector<uint8_t> recv_buf(65536);
    auto start = std::chrono::steady_clock::now();
    auto result = transport.recv(recv_buf.data(), recv_buf.size(), 0.5);
    auto elapsed = std::chrono::steady_clock::now() - start;

    EXPECT_EQ(result.status, RecvStatus::Timeout);
    EXPECT_GE(std::chrono::duration<double>(elapsed).count(), 0.4);
    EXPECT_LE(std::chrono::duration<double>(elapsed).count(), 1.0);

    transport.stop();
}

TEST_F(TCPTransportTest, RecvNonBlocking) {
    TCPTransport transport;
    transport.start();

    ASSERT_TRUE(transport.connect("127.0.0.1", server_port(), 5.0));

    // Non-blocking receive on empty queue should return immediately
    std::vector<uint8_t> recv_buf(65536);
    auto start = std::chrono::steady_clock::now();
    auto result = transport.recv(recv_buf.data(), recv_buf.size(), 0.0);
    auto elapsed = std::chrono::steady_clock::now() - start;

    EXPECT_EQ(result.status, RecvStatus::Timeout);
    EXPECT_LT(std::chrono::duration<double>(elapsed).count(), 0.1);

    transport.stop();
}

TEST_F(TCPTransportTest, Statistics) {
    TCPTransport transport;
    transport.start();

    auto stats_before = transport.stats();
    EXPECT_EQ(stats_before.messages_sent, 0u);
    EXPECT_EQ(stats_before.messages_received, 0u);

    ASSERT_TRUE(transport.connect("127.0.0.1", server_port(), 5.0));

    const char* msg = "Test message";
    transport.send(msg, std::strlen(msg));
    EXPECT_TRUE(transport.drain(2.0));

    // Wait for echo to arrive
    std::vector<uint8_t> recv_buf(65536);
    transport.recv(recv_buf.data(), recv_buf.size(), 1.0);

    auto stats_after = transport.stats();
    EXPECT_EQ(stats_after.messages_sent, 1u);
    EXPECT_EQ(stats_after.messages_received, 1u);
    EXPECT_GT(stats_after.bytes_sent, 0u);
    EXPECT_GT(stats_after.bytes_received, 0u);

    transport.stop();
}

TEST_F(TCPTransportTest, Drain) {
    TCPTransport transport;
    transport.start();

    ASSERT_TRUE(transport.connect("127.0.0.1", server_port(), 5.0));

    // Queue several messages
    for (int i = 0; i < 5; ++i) {
        std::string msg = "Message " + std::to_string(i);
        transport.send(msg.data(), msg.size());
    }

    // Drain should complete
    EXPECT_TRUE(transport.drain(5.0));

    // Queue should be empty
    EXPECT_EQ(transport.stats().send_queue_size, 0u);

    transport.stop();
}

TEST_F(TCPTransportTest, DisconnectDuringRecv) {
    TCPTransport transport;
    transport.start();

    ASSERT_TRUE(transport.connect("127.0.0.1", server_port(), 5.0));

    // Start a blocking recv in another thread
    std::atomic<bool> recv_returned{false};
    RecvResult recv_result{0, RecvStatus::Timeout};

    std::thread recv_thread([&]() {
        std::vector<uint8_t> recv_buf(65536);
        recv_result = transport.recv(recv_buf.data(), recv_buf.size(), 5.0);
        recv_returned = true;
    });

    // Give the recv thread time to start waiting
    std::this_thread::sleep_for(std::chrono::milliseconds(100));

    // Disconnect should wake up the recv
    transport.disconnect();

    // Wait for recv to return
    recv_thread.join();

    EXPECT_TRUE(recv_returned);
    EXPECT_EQ(recv_result.status, RecvStatus::Disconnected);

    transport.stop();
}

TEST_F(TCPTransportTest, SendNotConnected) {
    TCPTransport transport;
    transport.start();

    // Should throw when not connected
    EXPECT_THROW(transport.send("test", 4), std::runtime_error);

    transport.stop();
}

TEST_F(TCPTransportTest, ConnectNotStarted) {
    TCPTransport transport;
    // Don't call start()

    // Should throw when transport not started
    EXPECT_THROW(transport.connect("127.0.0.1", 12345, 1.0), std::runtime_error);
}

TEST_F(TCPTransportTest, ConnectAlreadyConnected) {
    TCPTransport transport;
    transport.start();

    ASSERT_TRUE(transport.connect("127.0.0.1", server_port(), 5.0));

    // Second connect should throw
    EXPECT_THROW(transport.connect("127.0.0.1", server_port(), 5.0),
                 std::runtime_error);

    transport.stop();
}

TEST_F(TCPTransportTest, Metadata) {
    TCPTransport transport;
    transport.start();

    // Test name get/set
    EXPECT_EQ(transport.name(), "");
    transport.set_name("test-transport");
    EXPECT_EQ(transport.name(), "test-transport");

    // Before connect, remote info should be empty
    EXPECT_EQ(transport.remote_host(), "");
    EXPECT_EQ(transport.remote_port(), 0);

    ASSERT_TRUE(transport.connect("127.0.0.1", server_port(), 5.0));

    // After connect, remote info should be available
    EXPECT_EQ(transport.remote_host(), "127.0.0.1");
    EXPECT_EQ(transport.remote_port(), server_port());

    // Local info should also be available
    EXPECT_FALSE(transport.local_host().empty());
    EXPECT_GT(transport.local_port(), 0);

    transport.stop();
}

// ============================================================================
// UDP Socket Tests
// ============================================================================

class UDPSocketTest : public ::testing::Test {};

TEST_F(UDPSocketTest, BindEphemeralPort) {
    UDPSocket socket;
    uint16_t port = socket.bind(0);
    EXPECT_GT(port, 0);
    EXPECT_EQ(socket.local_port(), port);
}

TEST_F(UDPSocketTest, BindSpecificPort) {
    UDPSocket socket;
    uint16_t port = socket.bind(57123);
    EXPECT_EQ(port, 57123);
    EXPECT_EQ(socket.local_port(), 57123);
}

TEST_F(UDPSocketTest, BindAlreadyBound) {
    UDPSocket socket;
    socket.bind(0);
    EXPECT_THROW(socket.bind(0), std::runtime_error);
}

TEST_F(UDPSocketTest, StartStop) {
    UDPSocket socket;
    socket.bind(0);
    EXPECT_FALSE(socket.is_running());

    socket.start();
    EXPECT_TRUE(socket.is_running());

    socket.stop();
    EXPECT_FALSE(socket.is_running());
}

TEST_F(UDPSocketTest, RecvTimeoutEmpty) {
    UDPSocket socket;
    socket.bind(0);
    socket.start();

    std::vector<uint8_t> recv_buf(65536);
    auto start = std::chrono::steady_clock::now();
    auto result = socket.recv(recv_buf.data(), recv_buf.size(), 0.1);
    auto elapsed = std::chrono::steady_clock::now() - start;

    EXPECT_EQ(result.status, RecvStatus::Timeout);
    EXPECT_GE(std::chrono::duration<double>(elapsed).count(), 0.08);

    socket.stop();
}

TEST_F(UDPSocketTest, SendWithoutConnectThrows) {
    UDPSocket socket;
    socket.bind(0);
    socket.start();

    // send() without connect() should throw
    EXPECT_THROW(socket.send("test", 4), std::runtime_error);

    socket.stop();
}

TEST_F(UDPSocketTest, SendToWithoutConnect) {
    UDPSocket socket;
    socket.bind(0);
    socket.start();

    // send_to() should work without connect()
    // This sends to localhost (won't be received, but shouldn't throw)
    EXPECT_TRUE(socket.send_to("test", 4, "127.0.0.1", 12345));

    socket.stop();
}

TEST_F(UDPSocketTest, ConnectDisconnect) {
    UDPSocket socket;
    socket.bind(0);
    socket.start();

    EXPECT_FALSE(socket.is_connected());
    EXPECT_EQ(socket.remote_host(), "");
    EXPECT_EQ(socket.remote_port(), 0);

    socket.connect("127.0.0.1", 12345);

    EXPECT_TRUE(socket.is_connected());
    EXPECT_EQ(socket.remote_host(), "127.0.0.1");
    EXPECT_EQ(socket.remote_port(), 12345);

    socket.disconnect();

    EXPECT_FALSE(socket.is_connected());
    EXPECT_EQ(socket.remote_host(), "");
    EXPECT_EQ(socket.remote_port(), 0);

    socket.stop();
}

TEST_F(UDPSocketTest, Metadata) {
    UDPSocket socket;
    socket.bind(0);

    // Test name get/set
    EXPECT_EQ(socket.name(), "");
    socket.set_name("udp-test");
    EXPECT_EQ(socket.name(), "udp-test");
}

TEST_F(UDPSocketTest, Statistics) {
    UDPSocket socket;
    socket.bind(0);
    socket.start();

    auto stats = socket.stats();
    EXPECT_EQ(stats.queue_size, 0u);
    EXPECT_EQ(stats.packets_received, 0u);
    EXPECT_EQ(stats.packets_dropped, 0u);
    EXPECT_EQ(stats.bytes_sent, 0u);
    EXPECT_EQ(stats.bytes_received, 0u);

    socket.stop();
}

TEST_F(UDPSocketTest, SendReceiveLoopback) {
    // Create two sockets - sender and receiver
    UDPSocket receiver;
    uint16_t recv_port = receiver.bind(0);
    receiver.start();

    UDPSocket sender;
    sender.bind(0);
    sender.start();

    // Send a packet
    const char* test_data = "Hello, UDP!";
    EXPECT_TRUE(sender.send_to(test_data, std::strlen(test_data),
                               "127.0.0.1", recv_port));

    // Receive the packet
    std::vector<uint8_t> recv_buf(65536);
    auto result = receiver.recv(recv_buf.data(), recv_buf.size(), 1.0);

    EXPECT_EQ(result.status, RecvStatus::Success);
    EXPECT_EQ(result.bytes, static_cast<ssize_t>(std::strlen(test_data)));
    EXPECT_EQ(std::memcmp(recv_buf.data(), test_data, std::strlen(test_data)), 0);

    // Check stats
    auto recv_stats = receiver.stats();
    EXPECT_EQ(recv_stats.packets_received, 1u);
    EXPECT_EQ(recv_stats.bytes_received, std::strlen(test_data));

    auto send_stats = sender.stats();
    EXPECT_EQ(send_stats.bytes_sent, std::strlen(test_data));

    sender.stop();
    receiver.stop();
}

#include <gtest/gtest.h>

#include <errno.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <unistd.h>
#include <atomic>
#include <chrono>
#include <cstring>
#include <random>
#include <thread>
#include <type_traits>
#include <vector>

#include "pybrid/transport/accepted_socket.h"
#include "pybrid/transport/tcp_server.h"
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

    std::vector<uint64_t> test_values = {0, 1, 127, 128, 255, 256, 1000, 0xFFFF, 0xFFFFFFFF, 0xFFFFFFFFFFFFFFFF};

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
            *server_io_, asio::ip::tcp::endpoint(asio::ip::tcp::v4(), 0));

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
            server_acceptor_->async_accept([this](const asio::error_code& ec, asio::ip::tcp::socket socket) {
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

    void do_read(std::shared_ptr<asio::ip::tcp::socket> socket, std::shared_ptr<std::vector<uint8_t>> buffer) {
        socket->async_read_some(
            asio::buffer(*buffer), [this, socket, buffer](const asio::error_code& ec, size_t bytes) {
                if (!ec && server_running_) {
                    // Echo back what we received
                    asio::async_write(
                        *socket,
                        asio::buffer(buffer->data(), bytes),
                        [this, socket, buffer](const asio::error_code& ec2, size_t /*bytes2*/) {
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
    EXPECT_THROW(transport.connect("127.0.0.1", server_port(), 5.0), std::runtime_error);

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
    EXPECT_TRUE(sender.send_to(test_data, std::strlen(test_data), "127.0.0.1", recv_port));

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

// ============================================================================
// AcceptedSocket RAII Tests (Fix #3)
// ============================================================================

// Helper: returns true if the given fd is closed (kernel reports EBADF).
static bool fd_is_closed(int fd) {
    errno = 0;
    int ret = ::fcntl(fd, F_GETFD);
    return ret == -1 && errno == EBADF;
}

class AcceptedSocketTest : public ::testing::Test {};

// After an AcceptedSocket goes out of scope the fd must be closed.
TEST_F(AcceptedSocketTest, DestructorClosesFd) {
    int fd = ::socket(AF_INET, SOCK_STREAM, 0);
    ASSERT_GE(fd, 0) << "Failed to create socket: " << strerror(errno);

    {
        AcceptedSocket sock(fd, "127.0.0.1", 9999);
        EXPECT_TRUE(sock.is_valid());
    }

    EXPECT_TRUE(fd_is_closed(fd)) << "Expected fd " << fd << " to be closed after AcceptedSocket destructor";
}

// Moving an AcceptedSocket transfers fd ownership; the moved-from object
// must not close the fd when it is destroyed.
TEST_F(AcceptedSocketTest, MoveTransfersFd) {
    int fd = ::socket(AF_INET, SOCK_STREAM, 0);
    ASSERT_GE(fd, 0) << "Failed to create socket: " << strerror(errno);

    AcceptedSocket a(fd, "127.0.0.1", 9999);
    EXPECT_TRUE(a.is_valid());

    AcceptedSocket b = std::move(a);

    // Source must be invalidated (no longer owns the fd).
    EXPECT_EQ(a.native_handle, -1);
    EXPECT_FALSE(a.is_valid());

    // Destination holds the fd.
    EXPECT_EQ(b.native_handle, fd);
    EXPECT_TRUE(b.is_valid());

    // After b is destroyed the fd must be closed.
    { AcceptedSocket sink = std::move(b); }

    EXPECT_TRUE(fd_is_closed(fd)) << "Expected fd " << fd << " to be closed after move-target AcceptedSocket destroyed";
}

// Move-assignment must close the previously held fd and steal the source fd.
TEST_F(AcceptedSocketTest, MoveAssignmentClosesExistingFd) {
    int fd1 = ::socket(AF_INET, SOCK_STREAM, 0);
    ASSERT_GE(fd1, 0) << "Failed to create socket fd1: " << strerror(errno);
    int fd2 = ::socket(AF_INET, SOCK_STREAM, 0);
    ASSERT_GE(fd2, 0) << "Failed to create socket fd2: " << strerror(errno);

    AcceptedSocket a(fd1, "127.0.0.1", 9998);
    AcceptedSocket b(fd2, "127.0.0.1", 9999);

    a = std::move(b);

    // fd1 must have been closed by the assignment (a dropped its old resource).
    EXPECT_TRUE(fd_is_closed(fd1)) << "Expected fd1 to be closed after move-assignment replaced it";

    // a now owns fd2.
    EXPECT_EQ(a.native_handle, fd2);

    // b is in moved-from state.
    EXPECT_EQ(b.native_handle, -1);
    EXPECT_FALSE(b.is_valid());

    // fd2 is still open (owned by a).
    EXPECT_FALSE(fd_is_closed(fd2));
}

// AcceptedSocket must NOT be copy-constructible or copy-assignable: copying
// a raw fd without an ownership protocol leads to double-close.
TEST_F(AcceptedSocketTest, CopyIsDeleted) {
    EXPECT_FALSE(std::is_copy_constructible<AcceptedSocket>::value)
        << "AcceptedSocket must not be copy-constructible (would cause double-close)";
    EXPECT_FALSE(std::is_copy_assignable<AcceptedSocket>::value)
        << "AcceptedSocket must not be copy-assignable (would cause double-close)";
}

// ============================================================================
// TCPServer pending_ drain Tests (Fix #3)
// ============================================================================

class TCPServerPendingDrainTest : public ::testing::Test {};

// When TCPServer is destroyed with queued but unconsumed AcceptedSockets, the
// destructor must close all pending fds.  We verify via the client side: a
// TCP connection whose server-side half is closed will have its blocking
// ::read() return 0 (EOF) rather than hanging indefinitely.
TEST_F(TCPServerPendingDrainTest, DestructorClosesPendingFds) {
    const int N_CLIENTS = 3;

    std::vector<int> client_fds;
    {
        TCPServer server;
        uint16_t port = server.bind(0);
        server.start();

        for (int i = 0; i < N_CLIENTS; ++i) {
            int cfd = ::socket(AF_INET, SOCK_STREAM, 0);
            ASSERT_GE(cfd, 0);

            sockaddr_in addr{};
            addr.sin_family = AF_INET;
            addr.sin_port = htons(port);
            addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);

            ASSERT_EQ(::connect(cfd, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)), 0)
                << "connect() failed: " << strerror(errno);

            client_fds.push_back(cfd);
        }

        std::this_thread::sleep_for(std::chrono::milliseconds(100));
        // server destroyed here — must close all pending server-side fds.
    }

    // Set a per-socket receive timeout so ::recv() won't block indefinitely if
    // the drain is missing (test would time out instead of hanging forever).
    // 500 ms is enough: after the fix, EOF arrives immediately; before the fix,
    // we want a fast failure rather than a 30-second hang.
    for (int cfd : client_fds) {
        struct timeval tv{};
        tv.tv_sec = 0;
        tv.tv_usec = 500000;
        ::setsockopt(cfd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
    }

    // Each client must see EOF (recv returns 0) because the server-side half
    // was closed by the TCPServer destructor draining pending_.
    for (int i = 0; i < N_CLIENTS; ++i) {
        int cfd = client_fds[i];
        char buf[16];
        ssize_t n = ::recv(cfd, buf, sizeof(buf), 0);
        EXPECT_EQ(n, 0) << "Client " << i << " expected EOF (0) after server destruction, got " << n
                        << " (errno=" << errno << " " << strerror(errno) << ")";
        ::close(cfd);
    }
}

// ============================================================================
// UDPSocket reset_buffers Tests (Fix #2)
// ============================================================================

class UDPSocketResetBuffersTest : public ::testing::Test {};

// After a burst that grows the recv_queue_ backing store, reset_buffers() must
// release the accumulated capacity: the queue becomes empty (all unread entries
// are discarded) and the fresh buffer starts at initial allocation.
TEST_F(UDPSocketResetBuffersTest, ResetBuffersReleasesBackingAfterBurst) {
    const int N_PACKETS = 512;

    UDPSocket receiver;
    uint16_t recv_port = receiver.bind(0);
    receiver.start();

    UDPSocket sender;
    sender.bind(0);
    sender.start();

    // Fill the recv_queue_ by sending N packets without consuming any.
    std::vector<uint8_t> pkt(64, 0xAB);
    for (int i = 0; i < N_PACKETS; ++i) {
        sender.send_to(pkt.data(), pkt.size(), "127.0.0.1", recv_port);
    }

    // Give the io thread time to push all packets into the queue.
    std::this_thread::sleep_for(std::chrono::milliseconds(200));

    // The queue must have grown: at least some packets arrived.
    EXPECT_GT(receiver.recv_queue_len(), 0u) << "No packets arrived in recv_queue_ before reset — burst did not work";

    // reset_buffers() swaps in a fresh buffer; in-flight entries are discarded.
    receiver.reset_buffers();

    // After reset the backing store is fresh: no items remain from before.
    EXPECT_EQ(receiver.recv_queue_len(), 0u)
        << "recv_queue_ still contains entries after reset_buffers() — old backing not released";

    sender.stop();
    receiver.stop();
}

// Concurrent reset_buffers() while the io thread is actively receiving must
// not crash or corrupt state.  After the concurrent phase, the socket must
// still be usable for normal send/recv.
TEST_F(UDPSocketResetBuffersTest, ResetBuffersSafeWithConcurrentReceives) {
    UDPSocket receiver;
    uint16_t recv_port = receiver.bind(0);
    receiver.start();

    UDPSocket sender;
    sender.bind(0);
    sender.start();

    std::atomic<bool> stop_sender{false};

    // Sender thread: continuously push small packets into the receiver.
    std::thread sender_thread([&]() {
        std::vector<uint8_t> pkt(32, 0xCD);
        while (!stop_sender.load(std::memory_order_relaxed)) {
            sender.send_to(pkt.data(), pkt.size(), "127.0.0.1", recv_port);
            std::this_thread::sleep_for(std::chrono::microseconds(100));
        }
    });

    // Let some packets accumulate.
    std::this_thread::sleep_for(std::chrono::milliseconds(50));

    // Call reset_buffers() while the sender is still running — must not crash.
    receiver.reset_buffers();

    // Brief additional activity after the reset.
    std::this_thread::sleep_for(std::chrono::milliseconds(50));

    stop_sender.store(true, std::memory_order_relaxed);
    sender_thread.join();

    // Socket must still be in a usable state (no crash, io thread alive).
    EXPECT_TRUE(receiver.is_running()) << "UDPSocket not running after concurrent reset_buffers() — io thread crashed";

    sender.stop();
    receiver.stop();
}

// ============================================================================
// TCPTransport reset_buffers Tests (Fix #2)
// ============================================================================

// Helper that creates a loopback pair: a TCPServer listening on an ephemeral
// port and a client TCPTransport connected to it.  Returns the server-side
// transport (from_accepted) and the client transport.
static std::pair<std::unique_ptr<TCPTransport>, std::unique_ptr<TCPTransport>> make_loopback_pair() {
    TCPServer server;
    uint16_t port = server.bind(0);
    server.start();

    // Client side
    auto client = std::make_unique<TCPTransport>();
    client->start();
    bool connected = client->connect("127.0.0.1", port, 5.0);
    if (!connected) {
        return {nullptr, nullptr};
    }

    // Give the server time to accept.
    std::this_thread::sleep_for(std::chrono::milliseconds(50));

    auto accepted = server.accept(0.5);
    if (!accepted.is_valid()) {
        return {nullptr, nullptr};
    }

    auto server_side = TCPTransport::from_accepted(std::move(accepted));
    if (!server_side) {
        return {nullptr, nullptr};
    }
    server_side->start();

    return {std::move(server_side), std::move(client)};
}

class TCPTransportResetBuffersTest : public ::testing::Test {};

// reset_buffers() must shrink recv_buffer_ back to its initial capacity
// (MAX_VARINT_SIZE + DEFAULT_TCP_MESSAGE_SIZE) after it has been allowed to
// grow, and must leave the transport in a functional state.
TEST_F(TCPTransportResetBuffersTest, ResetBuffersShrinksRecvBufferVector) {
    auto [server_side, client] = make_loopback_pair();
    ASSERT_NE(server_side, nullptr) << "Failed to create loopback pair";
    ASSERT_NE(client, nullptr) << "Failed to create loopback pair";

    // Initial capacity must equal the value set in the TCPTransport constructor.
    const size_t initial_cap = MAX_VARINT_SIZE + DEFAULT_TCP_MESSAGE_SIZE;
    EXPECT_EQ(server_side->recv_buffer_capacity(), initial_cap)
        << "Initial recv_buffer_ capacity does not match MAX_VARINT_SIZE + DEFAULT_TCP_MESSAGE_SIZE";

    // reset_buffers() on a transport that has not grown must also be a no-op
    // (capacity stays at initial) and must not throw or corrupt state.
    server_side->reset_buffers();

    EXPECT_EQ(server_side->recv_buffer_capacity(), initial_cap)
        << "recv_buffer_ capacity changed unexpectedly after reset on non-grown buffer";

    // Send messages through the client so bytes flow into server_side's
    // recv_buffer_.  Enough data to force at least one resize cycle
    // (i.e. fill the buffer before the io thread can drain it).
    // We send a burst of messages; the server does NOT consume them, so the
    // reassembly vector fills up and must double.
    //
    // Each varint-framed message has a 1-byte header + payload bytes.
    // We send N_MSGS * payload_size bytes to overflow the initial buffer.
    const size_t payload_size = 1024;
    const int N_MSGS = static_cast<int>(initial_cap / payload_size) + 4;
    std::vector<uint8_t> payload(payload_size, 0xEF);
    for (int i = 0; i < N_MSGS; ++i) {
        client->send(payload.data(), payload_size);
    }
    // Wait for data to flow into server_side recv_buffer_.
    std::this_thread::sleep_for(std::chrono::milliseconds(300));

    // After the burst, recv_buffer_capacity() may have grown above initial_cap
    // (the resize-on-full path doubles the buffer).  Whether it grew or not,
    // reset_buffers() must bring it back to initial_cap.
    server_side->reset_buffers();

    // Allow the posted reset closure to execute on the io_ thread.
    std::this_thread::sleep_for(std::chrono::milliseconds(50));

    EXPECT_EQ(server_side->recv_buffer_capacity(), initial_cap)
        << "recv_buffer_ capacity did not shrink to initial after reset_buffers()";

    // Transport must still be functional after reset.
    EXPECT_TRUE(server_side->is_running()) << "TCPTransport not running after reset_buffers()";

    client->stop();
    server_side->stop();
}

// Copyright (c) 2022-2025 anabrid GmbH
// SPDX-License-Identifier: MIT OR GPL-2.0-or-later

// Standalone benchmark: verifies that ClientSession instances are released
// when their TCP connections close (no accumulation across N connect/disconnect
// cycles). Not part of ctest — run manually or in a separate CI step.

#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <unistd.h>

#include <atomic>
#include <cerrno>
#include <chrono>
#include <cstring>
#include <future>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

#include "pybrid/proto/main.pb.h"
#include "pybrid/proxy/proxy_server.h"
#include "pybrid/proxy/proxy_session.h"
#include "pybrid/transport/tcp_server.h"
#include "pybrid/transport/tcp_transport.h"

using namespace anabrid::pybrid::native;

static constexpr int N_CLIENTS = 100;
static constexpr size_t ALIVE_TOLERANCE = 2;
static constexpr int QUIESCENCE_MS = 500;
static constexpr double HANDSHAKE_TIMEOUT = 10.0;
static constexpr size_t RECV_BUF = 65536;

static const std::string CARRIER_MAC = "aa-bb-cc-dd-ee-ff";
static const std::string CARRIER_PATH = "/" + CARRIER_MAC;

// Minimal mock backend — serves the three-message add_backend() handshake
// (ExtractCommand, ResetCommand, UdpDataStreamingCommand) then idles.
struct MockBackend {
    TCPServer server;
    std::unique_ptr<TCPTransport> transport;

    MockBackend() {
        server.bind(0);
        server.start();
    }

    ~MockBackend() {
        if (transport) transport->stop();
        server.stop();
    }

    uint16_t port() const { return server.local_port(); }

    void accept_and_handshake() {
        AcceptedSocket sock = server.accept(HANDSHAKE_TIMEOUT);
        if (!sock.is_valid()) throw std::runtime_error("MockBackend: accept timed out");
        transport = TCPTransport::from_accepted(std::move(sock));
        if (!transport) throw std::runtime_error("MockBackend: from_accepted returned null");
        transport->start();

        auto recv_msg = [&]() -> pb::MessageV1 {
            std::vector<uint8_t> buf(RECV_BUF);
            RecvResult r = transport->recv(buf.data(), buf.size(), HANDSHAKE_TIMEOUT);
            if (r.status != RecvStatus::Success || r.bytes == 0) throw std::runtime_error("MockBackend: recv failed");
            pb::Envelope env;
            if (!env.ParseFromArray(buf.data(), static_cast<int>(r.bytes)))
                throw std::runtime_error("MockBackend: parse failed");
            return env.message_v1();
        };

        auto send_msg = [&](const pb::MessageV1& msg) {
            pb::Envelope env;
            *env.mutable_message_v1() = msg;
            std::string bytes;
            env.SerializeToString(&bytes);
            transport->send(bytes.data(), bytes.size());
        };

        // 1. ExtractCommand
        pb::MessageV1 req = recv_msg();
        {
            pb::MessageV1 resp;
            resp.set_id(req.id());
            auto* item = resp.mutable_extract_response()->mutable_module()->add_items();
            item->mutable_entity_specification()->mutable_entity()->set_id(CARRIER_PATH);
            item->mutable_entity_specification()->mutable_entity()->set_class_(pb::Entity::CARRIER);
            send_msg(resp);
        }

        // 2. ResetCommand
        req = recv_msg();
        {
            pb::MessageV1 resp;
            resp.set_id(req.id());
            resp.mutable_reset_response()->mutable_entity()->set_path(CARRIER_PATH);
            send_msg(resp);
        }

        // 3. UdpDataStreamingCommand — accept it so the proxy moves forward.
        req = recv_msg();
        {
            pb::MessageV1 resp;
            resp.set_id(req.id());
            resp.mutable_success_message();
            send_msg(resp);
        }
    }
};

int main() {
    MockBackend backend;
    auto proxy = std::make_unique<ProxyServer>();
    proxy->set_session_timeout(0.1);

    // Start the backend handshake on a background thread before add_backend()
    // so the proxy's synchronous connect call does not race with accept().
    std::future<void> handshake = std::async(std::launch::async, [&]() { backend.accept_and_handshake(); });
    proxy->add_backend("127.0.0.1", backend.port());
    handshake.get();

    proxy->start("127.0.0.1", 0);
    const uint16_t proxy_port = proxy->local_port();

    const size_t baseline = ClientSession::alive_count();

    for (int i = 0; i < N_CLIENTS; ++i) {
        int fd = ::socket(AF_INET, SOCK_STREAM, 0);
        if (fd < 0) {
            std::cerr << "FAIL: socket() error: " << strerror(errno) << "\n";
            return 1;
        }

        struct sockaddr_in addr{};
        addr.sin_family = AF_INET;
        addr.sin_port = htons(proxy_port);
        ::inet_pton(AF_INET, "127.0.0.1", &addr.sin_addr);

        if (::connect(fd, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) != 0) {
            std::cerr << "FAIL: connect() on iteration " << i << ": " << strerror(errno) << "\n";
            ::close(fd);
            return 1;
        }

        // Brief pause so the proxy has time to accept and register the session.
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
        ::close(fd);
        // Allow the proxy's recv loop to detect EOF and deregister the session.
        std::this_thread::sleep_for(std::chrono::milliseconds(20));
    }

    std::this_thread::sleep_for(std::chrono::milliseconds(QUIESCENCE_MS));

    const size_t alive_after = ClientSession::alive_count();
    const size_t peak = ClientSession::alive_peak();

    proxy->stop();

    bool ok = true;

    if (alive_after > baseline + ALIVE_TOLERANCE) {
        std::cerr << "FAIL: sessions leaked — alive_count went from " << baseline << " to " << alive_after << " after "
                  << N_CLIENTS << " connections (tolerance " << ALIVE_TOLERANCE << ")\n";
        ok = false;
    }

    if (peak <= baseline) {
        std::cerr << "FAIL: alive_peak() never exceeded baseline (" << baseline
                  << ") — sessions may not have been created at all\n";
        ok = false;
    }

    if (ok) {
        std::cout << "PASS: " << N_CLIENTS << " connect/disconnect cycles, "
                  << "peak=" << peak << ", alive_after=" << alive_after << " (baseline=" << baseline << ")\n";
        return 0;
    }
    return 1;
}

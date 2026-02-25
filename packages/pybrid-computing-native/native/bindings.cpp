#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <pybind11/functional.h>

#include "pybrid/buffer.h"
#include "pybrid/lockfree_buffer.h"
#include "pybrid/transport/tcp_transport.h"
#include "pybrid/transport/tcp_server.h"
#include "pybrid/transport/udp_socket.h"
#include "pybrid/channel/data_channel.h"
#include "pybrid/channel/sample_decoding_data_channel.h"
#include "pybrid/channel/control_channel.h"
#include "pybrid/proxy/proxy_server.h"
#include "pybrid/proto/main.pb.h"

namespace py = pybind11;
using namespace anabrid::pybrid::native;

PYBIND11_MODULE(_impl, m) {
    m.doc() = "Native transport layer for high-performance UDP/TCP networking";

    // MessageTooLargeError derives from ValueError for semantic clarity
    static py::exception<MessageTooLargeError> exc_message_too_large(
        m, "MessageTooLargeError", PyExc_ValueError
    );
    static py::exception<BufferFullError> exc_buffer_full(
        m, "BufferFullError", PyExc_RuntimeError
    );

    py::enum_<BufferType>(m, "BufferType", "Available buffer implementation types")
        .value("LockFree", BufferType::LockFree,
               "Lock-free buffer using moodycamel::ConcurrentQueue (default)");

    py::enum_<RecvStatus>(m, "RecvStatus", "Status codes for receive operations")
        .value("Success", RecvStatus::Success, "Data received successfully")
        .value("Timeout", RecvStatus::Timeout, "No data available within timeout")
        .value("Disconnected", RecvStatus::Disconnected, "Connection closed");

    py::class_<RecvResult>(m, "RecvResult", "Result from a receive operation")
        .def_readonly("bytes", &RecvResult::bytes,
                      "Bytes received (>0 on success, 0 otherwise)")
        .def_readonly("status", &RecvResult::status,
                      "Status code indicating outcome")
        .def("__repr__", [](const RecvResult& r) {
            std::string status_str;
            switch (r.status) {
                case RecvStatus::Success: status_str = "Success"; break;
                case RecvStatus::Timeout: status_str = "Timeout"; break;
                case RecvStatus::Disconnected: status_str = "Disconnected"; break;
            }
            return "<RecvResult bytes=" + std::to_string(r.bytes) +
                   " status=" + status_str + ">";
        });

    py::class_<AcceptedSocket>(m, "AcceptedSocket",
        "Information about an accepted TCP connection.")
        .def(py::init<>())
        .def(py::init<int, const std::string&, uint16_t>(),
             py::arg("native_handle"), py::arg("remote_host"), py::arg("remote_port"))
        .def_readonly("native_handle", &AcceptedSocket::native_handle,
                      "Native socket file descriptor")
        .def_readonly("remote_host", &AcceptedSocket::remote_host,
                      "Remote peer IP address")
        .def_readonly("remote_port", &AcceptedSocket::remote_port,
                      "Remote peer port")
        .def("is_valid", &AcceptedSocket::is_valid,
             "Check if this accepted socket contains a valid handle")
        .def("__repr__", [](const AcceptedSocket& s) {
            return "<AcceptedSocket handle=" + std::to_string(s.native_handle) +
                   " remote=" + s.remote_host + ":" + std::to_string(s.remote_port) + ">";
        });

    py::class_<UDPStats>(m, "UDPStats", "Statistics for UDP transport monitoring")
        .def_readonly("queue_size", &UDPStats::queue_size,
                      "Current items in receive queue")
        .def_readonly("packets_received", &UDPStats::packets_received,
                      "Total packets received")
        .def_readonly("packets_dropped", &UDPStats::packets_dropped,
                      "Packets dropped due to full queue")
        .def_readonly("bytes_sent", &UDPStats::bytes_sent,
                      "Total bytes sent")
        .def_readonly("bytes_received", &UDPStats::bytes_received,
                      "Total bytes received")
        .def("__repr__", [](const UDPStats& s) {
            return "<UDPStats queue=" + std::to_string(s.queue_size) +
                   " pkts_recv=" + std::to_string(s.packets_received) +
                   " pkts_drop=" + std::to_string(s.packets_dropped) +
                   " bytes_sent=" + std::to_string(s.bytes_sent) +
                   " bytes_recv=" + std::to_string(s.bytes_received) + ">";
        });

    py::class_<TCPStats>(m, "TCPStats", "Statistics for TCP transport monitoring")
        .def_readonly("recv_queue_size", &TCPStats::recv_queue_size,
                      "Current items in receive queue")
        .def_readonly("send_queue_size", &TCPStats::send_queue_size,
                      "Current items in send queue")
        .def_readonly("bytes_sent", &TCPStats::bytes_sent,
                      "Total bytes sent")
        .def_readonly("bytes_received", &TCPStats::bytes_received,
                      "Total bytes received")
        .def_readonly("messages_sent", &TCPStats::messages_sent,
                      "Total messages sent")
        .def_readonly("messages_received", &TCPStats::messages_received,
                      "Total messages received")
        .def_readonly("messages_dropped", &TCPStats::messages_dropped,
                      "Messages dropped due to full receive queue")
        .def("__repr__", [](const TCPStats& s) {
            return "<TCPStats recv_queue=" + std::to_string(s.recv_queue_size) +
                   " send_queue=" + std::to_string(s.send_queue_size) +
                   " msgs_sent=" + std::to_string(s.messages_sent) +
                   " msgs_recv=" + std::to_string(s.messages_received) +
                   " msgs_dropped=" + std::to_string(s.messages_dropped) + ">";
        });

    py::class_<UDPSocket>(m, "UDPSocket",
                             R"doc(
High-performance UDP socket with single-port binding.

Provides a UDP networking layer using standalone Asio that runs independently
of Python's asyncio event loop. A dedicated io_context runs in its own thread.

Args:
    buffer_type: Buffer implementation to use (default: BufferType.LockFree).

Example:
    >>> socket = UDPSocket()
    >>> port = socket.bind(0)  # Ephemeral port
    >>> socket.start()
    >>> try:
    ...     buf = bytearray(65536)
    ...     result = socket.recv(buf, timeout=1.0)
    ...     if result.status == RecvStatus.Success:
    ...         data = buf[:result.bytes]
    ... finally:
    ...     socket.stop()

Context Manager:
    >>> with UDPSocket() as socket:
    ...     socket.bind(0)
    ...     socket.start()
    ...     # use socket
)doc")
        .def(py::init<BufferType>(), py::arg("buffer_type") = BufferType::LockFree,
             "Construct a UDPSocket with specified buffer type")
        .def("start", &UDPSocket::start,
             "Start the io_context thread.")
        .def("stop", &UDPSocket::stop,
             "Stop the io_context and join the thread.")
        .def("is_running", &UDPSocket::is_running,
             "Check if the transport is running.")
        .def("bind", &UDPSocket::bind, py::arg("port") = 0,
             R"doc(
Bind to a UDP port.

Args:
    port: Port number to bind (0 for ephemeral/random port).

Returns:
    The actual bound port number.

Raises:
    RuntimeError: If bind fails or already bound.
)doc")
        .def("close", &UDPSocket::close,
             "Close the bound UDP socket.")
        .def("local_port", &UDPSocket::local_port,
             "Get the local port number (0 if not bound).")
        .def("connect", &UDPSocket::connect, py::arg("host"), py::arg("port"),
             R"doc(
Set the remote endpoint for connected mode.

After calling connect(), send() can be used instead of send_to().

Args:
    host: IP address (raw IP only, no DNS resolution).
    port: Remote port number.

Raises:
    RuntimeError: If host is invalid.
)doc")
        .def("disconnect", &UDPSocket::disconnect,
             "Clear the remote endpoint.")
        .def("is_connected", &UDPSocket::is_connected,
             "Check if a remote endpoint is set.")
        .def(
            "recv",
            [](UDPSocket& self, py::buffer buf, double timeout) {
                py::buffer_info info = buf.request(/*writable=*/true);
                RecvResult result;
                {
                    py::gil_scoped_release release;
                    result = self.recv(info.ptr, info.size * info.itemsize, timeout);
                }
                return result;
            },
            py::arg("buffer"), py::arg("timeout"),
            R"doc(
Receive a UDP packet into a buffer.

Blocks until data is available, timeout expires, or socket closes.
Releases the GIL while waiting.

Args:
    buffer: A writable buffer (e.g., bytearray) to receive data into.
    timeout: Timeout in seconds (0 = non-blocking).

Returns:
    RecvResult with bytes received and status code.

Example:
    buf = bytearray(65536)
    result = transport.recv(buf, timeout=1.0)
    if result.status == RecvStatus.Success:
        data = buf[:result.bytes]
)doc")
        .def(
            "recv_nowait",
            [](UDPSocket& self, py::buffer buf) {
                py::buffer_info info = buf.request(/*writable=*/true);
                return self.recv(info.ptr, info.size * info.itemsize, 0.0);
            },
            py::arg("buffer"),
            R"doc(
Receive a UDP packet without blocking.

Args:
    buffer: A writable buffer to receive data into.

Returns:
    RecvResult with bytes received and status (Timeout if no data).
)doc")
        .def(
            "send",
            [](UDPSocket& self, py::bytes data) {
                std::string_view sv = data;
                return self.send(sv.data(), sv.size());
            },
            py::arg("data"),
            R"doc(
Send data to the connected remote endpoint.

Requires connect() to be called first.

Args:
    data: Data to send.

Returns:
    True if data was sent successfully.

Raises:
    RuntimeError: If not connected or not bound.
)doc")
        .def(
            "send_to",
            [](UDPSocket& self, py::bytes data, const std::string& host,
               uint16_t port) {
                std::string_view sv = data;
                return self.send_to(sv.data(), sv.size(), host, port);
            },
            py::arg("data"), py::arg("host"), py::arg("port"),
            R"doc(
Send data to a specific destination.

Does not require connect() - sends directly to the specified endpoint.

Args:
    data: Data to send.
    host: Destination IP address.
    port: Destination port number.

Returns:
    True if data was sent successfully.

Raises:
    RuntimeError: If not bound or host is invalid.
)doc")
        .def("name", &UDPSocket::name, "Get the transport's name.")
        .def("set_name", &UDPSocket::set_name, py::arg("name"),
             "Set the transport's name.")
        .def("remote_host", &UDPSocket::remote_host,
             "Get the connected remote host address.")
        .def("remote_port", &UDPSocket::remote_port,
             "Get the connected remote port.")
        .def("stats", &UDPSocket::stats,
             "Get current transport statistics.")
        .def("__enter__", [](UDPSocket& self) -> UDPSocket& {
            return self;
        })
        .def("__exit__",
             [](UDPSocket& self, py::object /*exc_type*/,
                py::object /*exc_val*/, py::object /*exc_tb*/) { self.stop(); });

    py::class_<TCPServer>(m, "TCPServer",
        R"doc(
TCP server that accepts connections and returns socket handles.

Threading Model:
- 1 C++ thread runs the server's io_context (accepting only)
- Python creates TCPTransport instances from accepted sockets

Example:
    >>> server = TCPServer()
    >>> port = server.bind(5732)
    >>> server.start()
    >>> try:
    ...     accepted = server.accept(timeout=1.0)
    ...     if accepted.is_valid():
    ...         transport = TCPTransport.from_accepted(accepted)
    ...         transport.start()
    ...         # use transport...
    ... finally:
    ...     server.stop()
)doc")
        .def(py::init<>())
        .def("bind", &TCPServer::bind, py::arg("port") = 0,
             R"doc(
Bind to a TCP port.

Args:
    port: Port number to bind (0 for ephemeral/random port).

Returns:
    The actual bound port number.

Raises:
    RuntimeError: If bind fails or already bound.
)doc")
        .def("start", &TCPServer::start,
             "Start accepting connections.")
        .def("stop", &TCPServer::stop,
             "Stop accepting and close server socket.")
        .def("is_running", &TCPServer::is_running,
             "Check if the server is running.")
        .def("local_port", &TCPServer::local_port,
             "Get the local port number.")
        .def("accept", [](TCPServer& self, double timeout) {
            AcceptedSocket accepted;
            {
                py::gil_scoped_release release;
                accepted = self.accept(timeout);
            }
            return accepted;
        }, py::arg("timeout"),
           R"doc(
Accept the next pending connection.

Blocks until a connection is available or timeout expires.
Releases the GIL while waiting.

Args:
    timeout: Timeout in seconds (0 = non-blocking).

Returns:
    AcceptedSocket with valid handle, or invalid socket on timeout.
)doc")
        .def("__enter__", [](TCPServer& self) -> TCPServer& { return self; })
        .def("__exit__", [](TCPServer& self, py::object, py::object, py::object) {
            self.stop();
        });

    py::class_<TCPTransport>(m, "TCPTransport",
                             R"doc(
High-performance TCP transport with varint message framing.

Provides a TCP networking layer using standalone Asio that runs independently
of Python's asyncio event loop. A dedicated io_context runs in its own thread.

Args:
    buffer_type: Buffer implementation to use (default: BufferType.LockFree).

Example:
    >>> transport = TCPTransport()
    >>> transport.start()
    >>> if transport.connect("127.0.0.1", 8080, timeout=5.0):
    ...     transport.send(b"Hello!")
    ...     buf = bytearray(65536)
    ...     result = transport.recv(buf, timeout=1.0)
    ...     if result.status == RecvStatus.Success:
    ...         data = buf[:result.bytes]
    >>> transport.stop()

Context Manager:
    >>> with TCPTransport() as transport:
    ...     transport.start()
    ...     transport.connect("127.0.0.1", 8080)
    ...     # use transport
)doc")
        .def(py::init<BufferType>(), py::arg("buffer_type") = BufferType::LockFree,
             "Construct a TCPTransport with specified buffer type")
        .def("start", &TCPTransport::start,
             "Start the io_context thread.")
        .def("stop", &TCPTransport::stop,
             "Stop the io_context and join the thread.")
        .def("is_running", &TCPTransport::is_running,
             "Check if the transport is running.")
        .def(
            "connect",
            [](TCPTransport& self, const std::string& host, uint16_t port,
               double timeout) {
                bool result;
                {
                    py::gil_scoped_release release;
                    result = self.connect(host, port, timeout);
                }
                return result;
            },
            py::arg("host"), py::arg("port"), py::arg("timeout") = DEFAULT_TCP_CONNECT_TIMEOUT,
            R"doc(
Connect to a TCP server.

Blocks until connected or timeout expires. Releases the GIL while waiting.

Args:
    host: IP address (raw IP only, no DNS resolution).
    port: Port number.
    timeout: Connection timeout in seconds (default: 5).

Returns:
    True if connected successfully, False on timeout or error.

Raises:
    RuntimeError: If already connected or transport not running.
)doc")
        .def("disconnect", &TCPTransport::disconnect,
             "Disconnect the TCP connection. No-op if not connected.")
        .def("is_connected", &TCPTransport::is_connected,
             "Check if TCP is connected.")
        .def(
            "recv",
            [](TCPTransport& self, py::buffer buf, double timeout) {
                py::buffer_info info = buf.request(/*writable=*/true);
                RecvResult result;
                {
                    py::gil_scoped_release release;
                    result = self.recv(info.ptr, info.size * info.itemsize, timeout);
                }
                return result;
            },
            py::arg("buffer"), py::arg("timeout"),
            R"doc(
Receive a TCP message into a buffer.

Blocks until data is available, timeout expires, or connection closes.
Releases the GIL while waiting.

Args:
    buffer: A writable buffer (e.g., bytearray) to receive data into.
    timeout: Timeout in seconds (0 = non-blocking).

Returns:
    RecvResult with bytes received and status code.

Example:
    buf = bytearray(65536)
    result = transport.recv(buf, timeout=1.0)
    if result.status == RecvStatus.Success:
        data = buf[:result.bytes]
)doc")
        .def(
            "recv_nowait",
            [](TCPTransport& self, py::buffer buf) {
                py::buffer_info info = buf.request(/*writable=*/true);
                return self.recv(info.ptr, info.size * info.itemsize, 0.0);
            },
            py::arg("buffer"),
            R"doc(
Receive a TCP message without blocking.

Args:
    buffer: A writable buffer to receive data into.

Returns:
    RecvResult with bytes received and status (Timeout if no data).
)doc")
        .def(
            "send",
            [](TCPTransport& self, py::bytes data) {
                std::string_view sv = data;
                return self.send(sv.data(), sv.size());
            },
            py::arg("data"),
            R"doc(
Send a message via TCP with varint framing.

The message is queued for async transmission.

Args:
    data: Message data to send.

Returns:
    True if message was queued successfully, False if queue full.

Raises:
    RuntimeError: If not connected or message too large.
)doc")
        .def(
            "drain",
            [](TCPTransport& self, double timeout) {
                bool result;
                {
                    py::gil_scoped_release release;
                    result = self.drain(timeout);
                }
                return result;
            },
            py::arg("timeout"),
            R"doc(
Wait for TCP send queue to drain.

Blocks until all pending sends are complete or timeout expires.
Releases the GIL while waiting.

Args:
    timeout: Maximum time to wait in seconds.

Returns:
    True if queue drained, False if timeout.
)doc")
        .def("name", &TCPTransport::name, "Get the transport's name.")
        .def("set_name", &TCPTransport::set_name, py::arg("name"),
             "Set the transport's name.")
        .def("remote_host", &TCPTransport::remote_host,
             "Get the connected remote host address.")
        .def("remote_port", &TCPTransport::remote_port,
             "Get the connected remote port.")
        .def("local_host", &TCPTransport::local_host,
             "Get the local host address.")
        .def("local_port", &TCPTransport::local_port,
             "Get the local port.")
        .def("stats", &TCPTransport::stats,
             "Get current transport statistics.")
        .def_static("from_accepted", [](const AcceptedSocket& accepted, BufferType buffer_type) {
            auto transport = TCPTransport::from_accepted(accepted, buffer_type);
            if (!transport) {
                throw std::runtime_error("Failed to create transport from accepted socket");
            }
            return transport.release();  // pybind11 takes ownership
        }, py::arg("accepted"), py::arg("buffer_type") = BufferType::LockFree,
           py::return_value_policy::take_ownership,
           R"doc(
Create a TCPTransport from an accepted connection.

Factory method for server-side connections. Creates a new TCPTransport
that adopts an existing native socket handle.

Args:
    accepted: AcceptedSocket from TCPServer.accept().
    buffer_type: Buffer implementation to use (default: LockFree).

Returns:
    A new TCPTransport instance. Call start() to begin I/O.

Raises:
    RuntimeError: If the accepted socket is invalid.

Example:
    >>> accepted = server.accept(timeout=1.0)
    >>> if accepted.is_valid():
    ...     transport = TCPTransport.from_accepted(accepted)
    ...     transport.start()
)doc")
        .def("__enter__", [](TCPTransport& self) -> TCPTransport& {
            return self;
        })
        .def("__exit__",
             [](TCPTransport& self, py::object /*exc_type*/,
                py::object /*exc_val*/, py::object /*exc_tb*/) { self.stop(); });

    py::enum_<pb::RunState>(m, "RunState", "Run state of the analog computer")
        .value("NEW", pb::NEW)
        .value("ERROR", pb::ERROR)
        .value("DONE", pb::DONE)
        .value("QUEUED", pb::QUEUED)
        .value("TAKE_OFF", pb::TAKE_OFF)
        .value("IC", pb::IC)
        .value("OP", pb::OP)
        .value("OP_END", pb::OP_END)
        .value("TMP_HALT", pb::TMP_HALT);

    py::class_<DataChannel>(m, "DataChannel",
        "Abstract base class for data streaming channels")
        .def("set_udp_endpoint", &DataChannel::set_udp_endpoint,
             py::arg("host"), py::arg("port"),
             "Set the remote UDP endpoint to receive data from.")
        .def("set_udp_bind_port", &DataChannel::set_udp_bind_port,
             py::arg("port"),
             "Set the local UDP port to bind to.")
        .def("set_tcp_transport", &DataChannel::set_tcp_transport,
             py::arg("transport"), py::keep_alive<1, 2>(),
             "Set the TCP transport for fallback mode.")
        .def("set_control_response_callback", [](DataChannel& self, py::function callback) {
            self.set_control_response_callback([callback](std::vector<uint8_t> data) {
                py::gil_scoped_acquire acquire;
                callback(py::bytes(reinterpret_cast<const char*>(data.data()), data.size()));
            });
        }, py::arg("callback"),
           "Set callback for control responses received during TCP fallback.")
        .def("set_control_channel", &DataChannel::set_control_channel,
             py::arg("cc"), py::keep_alive<1, 2>(),
             "Set the ControlChannel used for UDP negotiation. Must be called before start().")
        .def("set_negotiation_timeout", &DataChannel::set_negotiation_timeout,
             py::arg("secs"),
             "Set the negotiation timeout in seconds for negotiate_udp() (default: 5.0).")
        .def("negotiate_udp", [](DataChannel& self, uint16_t local_port) {
            bool result;
            {
                py::gil_scoped_release release;
                result = self.negotiate_udp(local_port);
            }
            return result;
        }, py::arg("local_port"),
           "Send UdpDataStreamingCommand through the control channel.")
        .def("start", [](DataChannel& self) {
            py::gil_scoped_release release;
            self.start();
        }, "Start the receive loop.")
        .def("stop", [](DataChannel& self) {
            py::gil_scoped_release release;
            self.stop();
        }, "Stop the receive loop.")
        .def("is_running", &DataChannel::is_running,
             "Check if the receive loop is running.")
        .def("is_using_tcp_fallback", &DataChannel::is_using_tcp_fallback,
             "Check if currently using TCP fallback.")
        .def("current_run_state", &DataChannel::current_run_state,
             "Get the current run state.")
        .def("on_run_state_change", [](DataChannel& self, py::function callback) {
            self.on_run_state_change([callback](pb::RunState state) {
                py::gil_scoped_acquire acquire;
                callback(state);
            });
        }, py::arg("callback"),
           "Register callback for run state changes.")
        .def("on_error", [](DataChannel& self, py::function callback) {
            self.on_error([callback](const std::string& msg) {
                py::gil_scoped_acquire acquire;
                callback(msg);
            });
        }, py::arg("callback"),
           "Register callback for errors.");

    py::class_<SampleDecodingDataChannel, DataChannel>(m,
        "SampleDecodingDataChannel",
        "DataChannel that decodes samples and pushes to queue (direct mode)")
        .def(py::init<>())
        .def("set_output_queue", &SampleDecodingDataChannel::set_output_queue,
             py::arg("queue"), py::keep_alive<1, 2>(),
             "Set the output queue for decoded sample blobs.")
        .def("__enter__", [](SampleDecodingDataChannel& self) -> SampleDecodingDataChannel& { return self; })
        .def("__exit__", [](SampleDecodingDataChannel& self, py::object, py::object, py::object) {
            py::gil_scoped_release release;
            self.stop();
        });

    py::class_<ControlChannel>(m, "ControlChannel",
        R"doc(
TCP-based control channel with request-response correlation.

Wraps a TCPTransport and provides structured message exchange with UUID-based
request-response correlation. Runs a C++ receive thread to avoid GIL contention.

Example:
    >>> channel = ControlChannel.create("127.0.0.1", 5732)
    >>> channel.start()
    >>> try:
    ...     entity = channel.describe()
    ...     config = channel.get_config("/")
    ... finally:
    ...     channel.stop()

Context Manager:
    >>> with ControlChannel.create("127.0.0.1", 5732) as channel:
    ...     channel.start()
    ...     entity = channel.describe()
)doc")

        // Factory method — release GIL during connection
        .def_static("create",
            [](const std::string& host, uint16_t port, double timeout) {
                std::unique_ptr<ControlChannel> channel;
                {
                    py::gil_scoped_release release;
                    channel = ControlChannel::create(host, port, timeout);
                }
                return channel.release();  // pybind11 takes ownership
            },
            py::arg("host"), py::arg("port"), py::arg("timeout") = 5.0,
            py::return_value_policy::take_ownership,
            R"doc(
Create a connected ControlChannel.

Connects a TCPTransport to host:port internally. Call start() to launch
the recv thread before sending or receiving messages.

Args:
    host:    Remote IP address (raw IP only, no DNS resolution).
    port:    Remote port number.
    timeout: Connection timeout in seconds (default: 5.0).

Returns:
    A new ControlChannel instance connected to the remote host.

Raises:
    RuntimeError: If the connection fails within the timeout.
)doc")
        .def("start", &ControlChannel::start,
             "Start the recv thread. Must be called after create().")
        .def("stop",
            [](ControlChannel& self) {
                py::gil_scoped_release release;
                self.stop();
            },
            "Stop the recv thread and close the transport. Blocks until the thread exits.")
        .def("stop_recv_thread",
            [](ControlChannel& self) {
                py::gil_scoped_release release;
                self.stop_recv_thread();
            },
            R"doc(
Stop only the receive thread, keeping the transport alive.

Used when DataChannel takes over the TCP transport for fallback streaming.
After this call, send_and_recv() still works if responses are routed back
via on_tcp_response().
)doc")
        .def("remote_host", &ControlChannel::remote_host,
             "Get the remote host address (empty if not connected).")
        .def("remote_port", &ControlChannel::remote_port,
             "Get the remote port number (0 if not connected).")
        .def("is_connected", &ControlChannel::is_connected,
             "Check if the underlying TCPTransport is connected.")
        .def("is_running", &ControlChannel::is_running,
             "Check if the recv thread is running.")
        .def("send",
            [](ControlChannel& self, py::bytes data) {
                std::string_view sv = data;
                pb::MessageV1 msg;
                if (!msg.ParseFromArray(sv.data(), sv.size())) {
                    throw std::runtime_error("Failed to parse MessageV1");
                }
                self.send(msg);
            },
            py::arg("data"),
            R"doc(
Send a serialized MessageV1 (fire-and-forget).

Args:
    data: Serialized MessageV1 bytes.

Raises:
    RuntimeError: If the transport is not connected or parsing fails.
)doc")
        .def("send_and_recv",
            [](ControlChannel& self, py::bytes data, double timeout) {
                std::string_view sv = data;
                pb::MessageV1 msg;
                if (!msg.ParseFromArray(sv.data(), sv.size())) {
                    throw std::runtime_error("Failed to parse MessageV1");
                }
                pb::MessageV1 response;
                {
                    py::gil_scoped_release release;
                    response = self.send_and_recv(msg, timeout);
                }
                std::string serialized;
                response.SerializeToString(&serialized);
                return py::bytes(serialized);
            },
            py::arg("data"), py::arg("timeout") = 5.0,
            R"doc(
Send a serialized MessageV1 and block until the matching response arrives.

The message must have a non-empty id field. The recv thread matches the
response by that id. Releases the GIL while waiting.

Args:
    data:    Serialized MessageV1 bytes (must have id set).
    timeout: Maximum time to wait for the response in seconds (default: 5.0).

Returns:
    Serialized MessageV1 response bytes.

Raises:
    RuntimeError: If timeout expires, transport disconnects, or parsing fails.
)doc")
        .def("register_callback",
            [](ControlChannel& self, int field_number, py::function callback) {
                self.register_callback(field_number, [callback](pb::MessageV1& msg) {
                    std::string serialized;
                    msg.SerializeToString(&serialized);
                    py::gil_scoped_acquire acquire;
                    callback(py::bytes(serialized));
                });
            },
            py::arg("field_number"), py::arg("callback"),
            R"doc(
Register a callback for a specific protobuf kind field number.

The callback is invoked by the recv thread for unsolicited notifications
and inbound requests from the peer. The callback receives serialized
MessageV1 bytes and must deserialize them with its own protobuf library.

Args:
    field_number: The oneof `kind` field number to register for.
    callback:     Callable receiving serialized MessageV1 bytes.
)doc")
        .def("unregister_callback", &ControlChannel::unregister_callback,
             py::arg("field_number"),
             "Unregister a previously registered callback for a kind field number.")
        .def("on_tcp_response",
            [](ControlChannel& self, py::bytes data) {
                std::string_view sv = data;
                std::vector<uint8_t> vec(sv.begin(), sv.end());
                self.on_tcp_response(std::move(vec));
            },
            py::arg("data"),
            R"doc(
Inject a raw serialized Envelope for processing.

Used by DataChannel in TCP fallback mode to route control responses back
to this channel.

Args:
    data: Raw serialized bytes of a pb::Envelope containing a MessageV1.
)doc")
        .def("transport", &ControlChannel::transport,
             py::return_value_policy::reference_internal,
             "Get a reference to the underlying TCPTransport.")
        .def("describe",
            [](ControlChannel& self, double timeout) {
                pb::Entity entity;
                {
                    py::gil_scoped_release release;
                    entity = self.describe(timeout);
                }
                std::string serialized;
                entity.SerializeToString(&serialized);
                return py::bytes(serialized);
            },
            py::arg("timeout") = 5.0,
            R"doc(
Send a DescribeCommand and return the serialized Entity response.

Releases the GIL while waiting for the response.

Args:
    timeout: Maximum time to wait in seconds (default: 5.0).

Returns:
    Serialized Entity bytes.

Raises:
    RuntimeError: On timeout or if the response contains an error.
)doc")
        .def("get_config",
            [](ControlChannel& self, const std::string& entity_path,
               bool recursive, double timeout) {
                pb::ConfigBundle bundle;
                {
                    py::gil_scoped_release release;
                    bundle = self.get_config(entity_path, recursive, timeout);
                }
                std::string serialized;
                bundle.SerializeToString(&serialized);
                return py::bytes(serialized);
            },
            py::arg("entity_path"), py::arg("recursive") = true,
            py::arg("timeout") = 5.0,
            R"doc(
Send an ExtractCommand and return the serialized ConfigBundle response.

Releases the GIL while waiting for the response.

Args:
    entity_path: The path of the entity whose config to extract.
    recursive:   If true, extract config of child entities recursively (default: True).
    timeout:     Maximum time to wait in seconds (default: 5.0).

Returns:
    Serialized ConfigBundle bytes.

Raises:
    RuntimeError: On timeout or if the response contains an error.
)doc")
        .def("set_config_bundle",
            [](ControlChannel& self, py::bytes data, double timeout) {
                std::string_view sv = data;
                pb::ConfigBundle bundle;
                if (!bundle.ParseFromArray(sv.data(), sv.size())) {
                    throw std::runtime_error("Failed to parse ConfigBundle");
                }
                bool result;
                {
                    py::gil_scoped_release release;
                    result = self.set_config_bundle(bundle, timeout);
                }
                return result;
            },
            py::arg("bundle_bytes"), py::arg("timeout") = 5.0,
            R"doc(
Send a ConfigCommand with the given bundle and return success.

Releases the GIL while waiting for the response.

Args:
    bundle_bytes: Serialized ConfigBundle bytes.
    timeout:      Maximum time to wait in seconds (default: 5.0).

Returns:
    True if the response does not contain an error_message.

Raises:
    RuntimeError: On timeout or if parsing fails.
)doc")
        .def("start_run_request",
            [](ControlChannel& self, py::bytes data, double timeout) {
                std::string_view sv = data;
                pb::StartRunCommand command;
                if (!command.ParseFromArray(sv.data(), sv.size())) {
                    throw std::runtime_error("Failed to parse StartRunCommand");
                }
                {
                    py::gil_scoped_release release;
                    self.start_run_request(command, timeout);
                }
            },
            py::arg("command_bytes"), py::arg("timeout") = 5.0,
            R"doc(
Send a StartRunCommand and wait for the start_run_response.

Waits for the run-accepted acknowledgement only, not for run completion.
Releases the GIL while waiting.

Args:
    command_bytes: Serialized StartRunCommand bytes.
    timeout:       Maximum time to wait in seconds (default: 5.0).

Raises:
    RuntimeError: On timeout, if the response is an error, or if parsing fails.
)doc")
        .def("reset",
            [](ControlChannel& self, bool keep_calibration, bool sync, double timeout) {
                py::gil_scoped_release release;
                self.reset(keep_calibration, sync, timeout);
            },
            py::arg("keep_calibration") = true, py::arg("sync") = true,
            py::arg("timeout") = 5.0,
            R"doc(
Send a ResetCommand and wait for the reset_response.

Releases the GIL while waiting for the response.

Args:
    keep_calibration: If true, calibration data is preserved across reset (default: True).
    sync:             If true, synchronisation is enabled during reset (default: True).
    timeout:          Maximum time to wait in seconds (default: 5.0).

Raises:
    RuntimeError: On timeout or if the response contains an error.
)doc")
        .def("authenticate",
            [](ControlChannel& self, const std::string& token, double timeout) {
                bool result;
                {
                    py::gil_scoped_release release;
                    result = self.authenticate(token, timeout);
                }
                return result;
            },
            py::arg("token"), py::arg("timeout") = 5.0,
            R"doc(
Send an AuthRequest with a bearer token and return success.

Releases the GIL while waiting for the response.

Args:
    token:   The bearer token to authenticate with.
    timeout: Maximum time to wait in seconds (default: 5.0).

Returns:
    True if the response does not contain an error_message.

Raises:
    RuntimeError: On timeout.
)doc")
        .def("__enter__", [](ControlChannel& self) -> ControlChannel& {
            return self;
        })
        .def("__exit__",
            [](ControlChannel& self, py::object /*exc_type*/,
               py::object /*exc_val*/, py::object /*exc_tb*/) {
                py::gil_scoped_release release;
                self.stop();
            });

    py::class_<ProxyServer>(m, "ProxyServer",
        R"doc(
Thin C++ relay between backend REDAC devices and TCP clients.

Manages N backend devices and M client sessions (FIFO, one active at a time).
No MAC address mapping — entity paths are forwarded as-is.

Example:
    >>> proxy = ProxyServer()
    >>> proxy.add_backend("192.168.1.10", 5732)
    >>> proxy.set_session_timeout(15.0)
    >>> proxy.start("0.0.0.0", 0)
    >>> port = proxy.local_port()
    >>> # ... proxy runs until stop() is called ...
    >>> proxy.stop()
)doc")
        .def(py::init<bool>(), py::arg("requires_auth") = false)
        .def("add_backend",
            [](ProxyServer& self, const std::string& host, uint16_t port,
               std::optional<uint32_t> stack, std::optional<uint32_t> carrier) {
                py::gil_scoped_release release;
                self.add_backend(host, port, stack, carrier);
            },
            py::arg("host"), py::arg("port"),
            py::arg("stack") = py::none(), py::arg("carrier") = py::none(),
            R"doc(
Connect to a backend device and prepare it for proxying.

Performs describe + reset handshake with the backend. Must be called before start().

If both stack and carrier are provided, injects location metadata into the cached
entity tree so clients can determine the carrier's physical rack position.

Args:
    host: Remote IP address of the backend device.
    port: Remote control port of the backend device.
    stack: Optional rack stack index (0-255).
    carrier: Optional carrier index within the stack (0-255).

Raises:
    RuntimeError: If connection or handshake fails.
)doc")
        .def("start",
            [](ProxyServer& self, const std::string& host, uint16_t port) {
                py::gil_scoped_release release;
                self.start(host, port);
            },
            py::arg("host") = "0.0.0.0", py::arg("port") = 0,
            R"doc(
Bind the server and start accepting client connections.

Args:
    host: Local bind address (default: "0.0.0.0").
    port: Local bind port (0 for ephemeral; query via local_port()).

Raises:
    RuntimeError: If bind fails or no backends have been added.
)doc")
        .def("stop",
            [](ProxyServer& self) {
                // Clear the Python sync callback while the GIL is still held so
                // that the py::function destructor does not run without the GIL
                // (which would be undefined behaviour in CPython).
                self.set_sync_callback({});
                py::gil_scoped_release release;
                self.stop();
            },
            "Stop the proxy server. Blocks until all threads exit.")
        .def("is_running", &ProxyServer::is_running,
             "Check whether the proxy server is running.")
        .def("local_port", &ProxyServer::local_port,
             "Get the local port the server is bound to.")
        .def("set_session_timeout", &ProxyServer::set_session_timeout,
             py::arg("secs"),
             R"doc(
Set the session idle timeout in seconds.

After a RunStateChangeMessage(DONE) is forwarded, the session expires if no
further activity occurs within this timeout. Default: 10.0 seconds.
Must be called before start().

Args:
    secs: Timeout in seconds. Must be positive.
)doc")
        .def("set_max_sessions", &ProxyServer::set_max_sessions,
             py::arg("n"),
             R"doc(
Set the maximum number of concurrent client sessions.

When this limit is reached, new connections are rejected with an
ErrorMessage("Server overloaded"). Default: 8.
Must be called before start().

Args:
    n: Maximum concurrent sessions. Must be at least 1.
)doc")
        .def("set_debug", &ProxyServer::set_debug,
             py::arg("enabled"),
             R"doc(
Enable or disable verbose debug logging to stderr.

When enabled, the proxy logs session lifecycle events: client connect/
disconnect, session activation, run start (with sample rate and OP-time),
errors from devices, and proxy-internal errors.

Args:
    enabled: True to enable debug logging, False to disable.
)doc")
        .def("set_sync_callback",
            [](ProxyServer& self, py::function callback) {
                self.set_sync_callback([callback](int group_id) {
                    py::gil_scoped_acquire acquire;
                    callback(group_id);
                });
            },
            py::arg("callback"),
            R"doc(
Register a USBSPI sync callback.

Called after all backends report TAKE_OFF during a StartRunCommand.
Must be called before start().

Args:
    callback: Callable receiving the run group_id (int).
)doc")
        .def("__enter__", [](ProxyServer& self) -> ProxyServer& { return self; })
        .def("__exit__", [](ProxyServer& self, py::object, py::object, py::object) {
            // Clear the Python sync callback while the GIL is still held (same
            // reason as stop() above — py::function destructor needs the GIL).
            self.set_sync_callback({});
            py::gil_scoped_release release;
            self.stop();
        });

    py::class_<IBuffer>(m, "IBuffer",
        "Abstract base class for variable-sized item buffers")
        .def("put",
            [](IBuffer& self, py::bytes data) {
                std::string_view sv = data;
                self.put(sv.size(), sv.data());
            },
            py::arg("data"),
            R"doc(
Put an item into the buffer.

Args:
    data: Bytes to store.

Raises:
    BufferFullError: If buffer cannot accept the item.
    MessageTooLargeError: If item exceeds maximum slot size.
)doc")
        .def("get",
            [](IBuffer& self, py::buffer buf, int buffer_size) {
                py::buffer_info info = buf.request(/*writable=*/true);
                size_t available = static_cast<size_t>(info.size * info.itemsize);
                size_t limit = static_cast<size_t>(buffer_size);
                if (limit > available) limit = available;
                return self.get(info.ptr, limit);
            },
            py::arg("buffer"), py::arg("buffer_size"),
            R"doc(
Get the next item from the buffer.

Args:
    buffer: A writable buffer (e.g. bytearray) to receive data into.
    buffer_size: Maximum number of bytes to read.

Returns:
    Number of bytes retrieved, or 0 if empty or buffer too small.
)doc")
        .def("len", &IBuffer::len,
             "Get the number of items currently in the buffer.")
        .def("size", &IBuffer::size,
             "Get the total byte size of item data in the buffer.");

    py::class_<LockFreeBuffer<>, IBuffer>(m, "LockFreeBuffer",
        R"doc(
Lock-free unbounded MPMC buffer for variable-sized items.

Uses moodycamel::ConcurrentQueue internally. Default template parameters:
SLOT_DATA_SIZE=512.  The buffer grows without bound as items are enqueued.

Example:
    >>> buf = LockFreeBuffer()
    >>> buf.put(b"hello")
    >>> assert buf.len() == 1
    >>> scratch = bytearray(64)
    >>> n = buf.get(scratch, 64)
    >>> assert bytes(scratch[:n]) == b"hello"
)doc")
        .def(py::init<>());

    // Larger slot variant for decoded sample blobs (up to 65536 bytes per slot).
    // Used as the output queue for SampleDecodingDataChannel, where blobs can be
    // significantly larger than 512 bytes (e.g. 4 channels * 100 samples * 8 bytes).
    py::class_<LockFreeBuffer<65536>, IBuffer>(m, "SampleLockFreeBuffer",
        R"doc(
Lock-free unbounded MPMC buffer with large slots for decoded sample blobs.

Same implementation as LockFreeBuffer but with SLOT_DATA_SIZE=65536
to accommodate decoded sample blobs that can be several KB.

Example:
    >>> buf = SampleLockFreeBuffer()
    >>> buf.put(b"x" * 4096)
    >>> assert buf.len() == 1
)doc")
        .def(py::init<>());

    m.attr("MAX_UDP_PACKET_SIZE") = MAX_UDP_PACKET_SIZE;
    m.attr("DEFAULT_TCP_MESSAGE_SIZE") = DEFAULT_TCP_MESSAGE_SIZE;
    m.attr("DEFAULT_TCP_CONNECT_TIMEOUT") = DEFAULT_TCP_CONNECT_TIMEOUT;
}

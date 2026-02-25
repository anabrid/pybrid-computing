# Copyright (c) 2022-2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
Shared fixtures for pybrid test suite.

This module provides common fixtures and helper functions used across
the test suite for testing REDAC, LUCIDAC, and Simulator functionality.

Environment Variables:
    TEST_REDAC_ENDPOINT: tcp://host:port for REDAC connection
    TEST_LUCIDAC_ENDPOINT: tcp://host:port for LUCIDAC connection
    TEST_SIMULATOR_ENDPOINT: tcp://host:port for Simulator connection
    PYBRID_TEST_PORT: Port for test servers (default: 6732)
"""
import os
import pytest
from pathlib import Path as PyPath
from urllib.parse import urlparse

TEST_DATA_DIR = PyPath(__file__).parent / "data"

# Default test port for DummyDAC servers
DEFAULT_TEST_PORT = 6732

# Device endpoint environment variable names for parameterized tests
DEVICE_ENDPOINTS = [
    "TEST_LUCIDAC_ENDPOINT",
    "TEST_REDAC_ENDPOINT",
    "TEST_SIMULATOR_ENDPOINT",
]


def get_test_port(index: int = 0) -> int:
    """
    Get the port to use for test servers (DummyDAC).

    Reads from PYBRID_TEST_PORT environment variable, defaulting to 6732.
    For multi-backend tests, use index to get sequential ports.

    Args:
        index: Backend index for multi-backend tests (0, 1, 2, ...).

    Returns:
        Port number for test servers (base_port + index).
    """
    return int(os.getenv("PYBRID_TEST_PORT", DEFAULT_TEST_PORT)) + index


def get_test_proxy_port() -> int:
    """
    Get the port to use for test proxy servers.

    Returns PYBRID_TEST_PORT + 1000 (default: 7732).

    Returns:
        Port number for proxy servers.
    """
    return get_test_port(0) + 1000


import json
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from typing import Generator


def wait_for_port(host: str, port: int, timeout: float = 10.0) -> bool:
    """
    Wait until a TCP port is reachable.

    Args:
        host: The host address to connect to.
        port: The port number to check.
        timeout: Maximum time to wait in seconds (default: 10).

    Returns:
        True if port became reachable, False if timeout reached.
    """
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            with socket.create_connection((host, port), timeout=1.0):
                return True
        except (ConnectionRefusedError, OSError, socket.timeout):
            time.sleep(0.1)
    return False


@contextmanager
def subprocess_dummy_dac(
    host: str = "127.0.0.1",
    port: int = None,
    virtual: bool = True,
) -> Generator[int, None, None]:
    """
    Start DummyDAC server as a subprocess and yield the port when ready.

    Args:
        host: Host address to bind to.
        port: Port to use. If None, uses get_test_port().
        virtual: Whether to use virtual MAC addresses.

    Yields:
        The port number the server is running on.

    Raises:
        RuntimeError: If server fails to start within 10 seconds.
    """
    if port is None:
        port = get_test_port()

    cmd = [
        sys.executable, "-m", "pybrid.cli.base",
        "dummy",
        "-h", host,
        "-p", str(port),
        "--virtual" if virtual else "--physical",
    ]

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        if not wait_for_port(host, port):
            stdout, stderr = "", ""
            try:
                stdout, stderr = process.communicate(timeout=1.0)
            except subprocess.TimeoutExpired:
                pass
            raise RuntimeError(
                f"DummyDAC server failed to start on {host}:{port}. "
                f"stdout: {stdout}, stderr: {stderr}"
            )
        yield port
    finally:
        process.terminate()
        try:
            process.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


@contextmanager
def subprocess_proxy(
    backend_host: str,
    backend_port: int,
    proxy_host: str = "127.0.0.1",
    proxy_port: int = None,
    mac_mapping: dict[str, str] = None,
    partition_config: dict = None,
) -> Generator[int, None, None]:
    """
    Start proxy server as a subprocess and yield the port when ready.

    The proxy connects to the backend DummyDAC, then exposes a proxy port.
    Uses a TemporaryDirectory to ensure temp files are only cleaned up
    AFTER the subprocess terminates, avoiding race conditions.

    Args:
        backend_host: Host of the backend DummyDAC.
        backend_port: Port of the backend DummyDAC.
        proxy_host: Host address for the proxy to bind to.
        proxy_port: Port for the proxy. If None, uses get_test_proxy_port().
        mac_mapping: Virtual MAC to path mapping. If None, uses default.
        partition_config: Partition configuration. If None, uses default.

    Yields:
        The port number the proxy is running on.

    Raises:
        RuntimeError: If proxy fails to start within 10 seconds.
    """
    if proxy_port is None:
        proxy_port = get_test_proxy_port()

    if mac_mapping is None:
        mac_mapping = {
            "EE-EE-EE-EE-EE-00": "/00-00-00-00-00-00",
            "EE-EE-EE-EE-EE-01": "/00-00-00-00-00-01",
        }

    if partition_config is None:
        partition_config = {"device": [list(mac_mapping.keys())]}

    with tempfile.TemporaryDirectory() as tmpdir:
        map_path = PyPath(tmpdir) / "mac_mapping.json"
        partition_path = PyPath(tmpdir) / "partition.json"

        with open(map_path, 'w') as f:
            json.dump(mac_mapping, f)
        with open(partition_path, 'w') as f:
            json.dump(partition_config, f)

        cmd = [
            sys.executable, "-m", "pybrid.cli.base",
            "redac",
            "-h", backend_host,
            "-p", str(backend_port),
            "--no-reset",
            "--standalone",
            "proxy",
            "-m", str(map_path),
            "-p", str(partition_path),
            proxy_host,
            str(proxy_port),
        ]

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        try:
            if not wait_for_port(proxy_host, proxy_port):
                stdout, stderr = "", ""
                try:
                    stdout, stderr = process.communicate(timeout=1.0)
                except subprocess.TimeoutExpired:
                    pass
                raise RuntimeError(
                    f"Proxy server failed to start on {proxy_host}:{proxy_port}. "
                    f"stdout: {stdout}, stderr: {stderr}"
                )
            yield proxy_port
        finally:
            process.terminate()
            try:
                process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        # TemporaryDirectory auto-cleans AFTER process terminates


def get_device_endpoint(env_var: str) -> tuple[str, int] | None:
    """
    Parse tcp://host:port format from environment variable.

    Args:
        env_var: Name of environment variable containing the endpoint URL.

    Returns:
        Tuple of (hostname, port) if environment variable is set, None otherwise.
        Uses port 5732 as default if no port is specified in the URL.
    """
    url = os.getenv(env_var)
    if not url:
        return None
    parsed = urlparse(url)
    port = parsed.port if parsed.port is not None else 5732
    return parsed.hostname, port


def make_daq_data(values: list, dtype: str, channel_count: int, sample_count: int,
                  scaling: list[tuple[int, float, float]] | None = None):
    """
    Create a pb.DaqData message for testing decode_data().

    Args:
        values: Raw data values to encode.
        dtype: NumPy dtype string (e.g., 'int16', 'uint16', 'float32').
        channel_count: Number of channels in the data.
        sample_count: Number of samples per channel.
        scaling: Optional list of (idx, gain, offset) tuples for scaling config.
                 If None, defaults to identity scaling for all channels.

    Returns:
        A pb.DaqData protobuf message configured with the specified data.
    """
    import numpy as np
    import pybrid.base.proto.main_pb2 as pb

    data_pb = pb.DaqData()
    data_pb.channel_count = channel_count
    data_pb.sample_count = sample_count
    data_pb.data = np.array(values, dtype=dtype).tobytes()

    if dtype.startswith('int'):
        data_pb.type.integer.signess = pb.IntegerType.Signedness.Signed
        data_pb.type.integer.bitwidth = int(dtype[3:])
    elif dtype.startswith('uint'):
        data_pb.type.integer.signess = pb.IntegerType.Signedness.Unsigned
        data_pb.type.integer.bitwidth = int(dtype[4:])
    elif dtype.startswith('float'):
        data_pb.type.float_.bitwidth = int(dtype[5:])

    if scaling is None:
        scaling = [(i, 1.0, 0.0) for i in range(channel_count)]
    for idx, gain, offset in scaling:
        s = data_pb.scaling.add()
        s.idx = idx
        s.gain = gain
        s.offset = offset

    return data_pb


def make_test_redac(num_carriers: int = 2):
    """
    Create a minimal REDAC computer for testing.

    This creates a REDAC instance with the specified number of carriers,
    each containing a single cluster. Uses virtual MAC addresses.

    Args:
        num_carriers: Number of carrier boards to create (default: 2).

    Returns:
        A REDAC instance configured for testing.
    """
    from pybrid.redac.computer import REDAC
    from pybrid.redac.carrier import Carrier
    from pybrid.redac.cluster import Cluster
    from pybrid.redac.blocks import UBlock, CBlock, IBlock
    from pybrid.redac.entities import Path
    from pybrid.base.utils.addressing import AddressingMap

    carriers = []
    for i in range(num_carriers):
        mac = AddressingMap.map_redac(i)
        carrier_path = Path.parse(mac)

        # Create minimal cluster with required blocks
        cluster_path = carrier_path / "0"
        cluster = Cluster(
            path=cluster_path,
            ublock=UBlock(path=cluster_path / "U"),
            cblock=CBlock(path=cluster_path / "C"),
            iblock=IBlock(path=cluster_path / "I"),
            shblock=None
        )

        carrier = Carrier(
            path=carrier_path,
            clusters=[cluster],
            tblock=None
        )
        carriers.append(carrier)

    return REDAC(entities=carriers)


@pytest.fixture(params=["virtual", "physical"])
async def dummy_dac(request):
    """
    DummyDAC server fixture. Parametrized for virtual/physical MAC modes.

    Yields a DummyDAC instance bound to localhost on the configured test port.
    Port is configurable via PYBRID_TEST_PORT env var (default: 6732).
    The fixture handles proper cleanup via async context manager.
    """
    from pybrid.mock import DummyDAC, DummyDACConfig, DummyDACMacMode

    mac_mode = DummyDACMacMode.VIRTUAL if request.param == "virtual" else DummyDACMacMode.PHYSICAL
    config = DummyDACConfig(mac_mode=mac_mode)
    async with DummyDAC("127.0.0.1", get_test_port(), config) as dac:
        yield dac


@pytest.fixture
async def dummy_dac_virtual():
    """
    DummyDAC with virtual MACs only.

    A simpler fixture for tests that do not need to test both MAC modes.
    Port is configurable via PYBRID_TEST_PORT env var (default: 6732).
    """
    from pybrid.mock import DummyDAC, DummyDACConfig, DummyDACMacMode

    config = DummyDACConfig(mac_mode=DummyDACMacMode.VIRTUAL)
    async with DummyDAC("127.0.0.1", get_test_port(), config) as dac:
        yield dac


@pytest.fixture
def simulator_endpoint():
    """
    Fixture providing Simulator endpoint from TEST_SIMULATOR_ENDPOINT.

    Skips test if environment variable is not set.

    Returns:
        Tuple of (hostname, port) for Simulator connection.
    """
    endpoint = get_device_endpoint("TEST_SIMULATOR_ENDPOINT")
    if endpoint is None:
        pytest.skip("TEST_SIMULATOR_ENDPOINT not set")
    return endpoint


def _endpoint_env_to_id(env_var: str) -> str:
    """
    Convert endpoint environment variable to a short test ID.

    Args:
        env_var: Environment variable name like TEST_LUCIDAC_ENDPOINT.

    Returns:
        Short ID like 'lucidac', 'redac', or 'simulator'.
    """
    mapping = {
        "TEST_LUCIDAC_ENDPOINT": "lucidac",
        "TEST_REDAC_ENDPOINT": "redac",
        "TEST_SIMULATOR_ENDPOINT": "simulator",
    }
    return mapping.get(env_var, env_var)


@pytest.fixture(params=DEVICE_ENDPOINTS, ids=lambda x: _endpoint_env_to_id(x))
def any_device_endpoint(request):
    """
    Parameterized fixture providing all available device endpoints.

    This fixture iterates over all device endpoint environment variables,
    skipping tests for devices that are not configured. Each device type
    appears as a separate test in the output.

    Returns:
        Tuple of (hostname, port, device_type) for device connection.
        device_type is one of: 'lucidac', 'redac', 'simulator'.
    """
    env_var = request.param
    endpoint = get_device_endpoint(env_var)
    if not endpoint:
        pytest.skip(f"{env_var} not set")
    device_type = _endpoint_env_to_id(env_var)
    return (*endpoint, device_type)


@pytest.fixture
def device_endpoint(request):
    """
    Generic device endpoint fixture for parametrized device tests.

    Use with pytest.mark.parametrize to test against different device
    endpoints specified by environment variables.

    Example:
        @pytest.mark.parametrize("device_endpoint", ["TEST_LUCIDAC_ENDPOINT"],
                                 indirect=True)
        def test_something(device_endpoint):
            host, port = device_endpoint
            ...
    """
    env_var = request.param
    endpoint = get_device_endpoint(env_var)
    if not endpoint:
        pytest.skip(f"{env_var} not set")
    return endpoint


@pytest.fixture
def harmonic_config():
    """
    Load minimal harmonic oscillator config for testing.

    Returns:
        Dict containing the harmonic oscillator configuration loaded from
        the test data directory.
    """
    import json

    config_path = TEST_DATA_DIR / "harmonic_legacy.json"
    with open(config_path) as f:
        return json.load(f)

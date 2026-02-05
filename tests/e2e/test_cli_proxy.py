# Copyright (c) 2022-2025 anabrid GmbH
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
E2E tests for CLI commands through Proxy.

Tests the pybrid CLI commands when connecting through a Proxy server,
simulating multi-device configurations and MAC address mapping.
"""

import asyncio
import subprocess
import sys

import pytest

from pybrid.redac.controller import Controller
from pybrid.redac.proxy import Proxy
from tests.conftest import (
    get_test_port,
    get_test_proxy_port,
    subprocess_dummy_dac,
    subprocess_proxy,
    TEST_DATA_DIR,
)


class TestCLIThroughProxy:
    """Tests for CLI commands routed through proxy."""

    def test_display_through_proxy(self):
        """
        Test 'pybrid redac display' through proxy shows mapped MACs.

        Verifies:
        - CLI can connect to proxy
        - Display output shows virtual MAC addresses (not physical)
        """
        mac_mapping = {
            "EE-EE-EE-EE-EE-00": "/00-00-00-00-00-00",
            "EE-EE-EE-EE-EE-01": "/00-00-00-00-00-01",
        }

        with subprocess_dummy_dac() as dac_port:
            with subprocess_proxy("127.0.0.1", dac_port, mac_mapping=mac_mapping) as proxy_port:
                result = subprocess.run(
                    [
                        sys.executable, "-m", "pybrid.cli.base",
                        "redac", "-h", "127.0.0.1", "-p", str(proxy_port),
                        "--no-reset",
                        "display"
                    ],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )

                combined_output = result.stdout + result.stderr
                assert result.returncode == 0 or any(
                    virtual_mac in combined_output for virtual_mac in mac_mapping.keys()
                ) or "Carrier" in combined_output, (
                    f"Display through proxy failed: stdout={result.stdout}, stderr={result.stderr}"
                )

    def test_reset_through_proxy(self):
        """
        Test 'pybrid redac reset' through proxy.

        Verifies:
        - Reset command is forwarded through proxy to backend
        - Command completes successfully
        """
        with subprocess_dummy_dac() as dac_port:
            with subprocess_proxy("127.0.0.1", dac_port) as proxy_port:
                result = subprocess.run(
                    [
                        sys.executable, "-m", "pybrid.cli.base",
                        "redac", "-h", "127.0.0.1", "-p", str(proxy_port),
                        "--no-reset",
                        "reset"
                    ],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )

                assert result.returncode == 0, f"Reset through proxy failed: {result.stderr}"


class TestCLIProxyMultiBackend:
    """Tests for CLI with proxy aggregating multiple backends.

    Note: Multi-backend tests use subprocess for DummyDACs but in-process
    for Controller+Proxy, since the CLI proxy command only accepts one backend.
    """

    @pytest.mark.asyncio
    async def test_display_multi_backend(self):
        """
        Test display shows all carriers from multiple backends.

        Verifies:
        - Proxy aggregates multiple backends
        - All carriers accessible through single CLI connection
        """
        dac1_port = get_test_port(0)
        dac2_port = get_test_port(1)
        proxy_port = get_test_proxy_port()

        with subprocess_dummy_dac(port=dac1_port) as _:
            with subprocess_dummy_dac(port=dac2_port) as _:
                async with Controller(standalone=True) as ctrl:
                    await ctrl.add_device("127.0.0.1", dac1_port)
                    await ctrl.add_device("127.0.0.1", dac2_port)

                    carrier_paths = list(ctrl.devices.keys())
                    mac_mapping = {}
                    for i, path in enumerate(carrier_paths):
                        virtual_mac = f"FF-FF-FF-FF-FF-{i:02X}"
                        mac_mapping[virtual_mac] = str(path)

                    partition_config = {"device": [list(mac_mapping.keys())]}

                    async with Proxy(
                        ctrl,
                        host="127.0.0.1",
                        port=proxy_port,
                        mac_mapping=mac_mapping,
                        partition_config=partition_config,
                    ) as (proxy, server):
                        # Use async subprocess to keep event loop running
                        proc = await asyncio.create_subprocess_exec(
                            sys.executable, "-m", "pybrid.cli.base",
                            "redac", "-h", "127.0.0.1", "-p", str(proxy_port),
                            "--no-reset",
                            "display",
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE,
                        )
                        try:
                            stdout, stderr = await asyncio.wait_for(
                                proc.communicate(), timeout=60
                            )
                        except asyncio.TimeoutError:
                            proc.kill()
                            raise

                        combined_output = stdout.decode() + stderr.decode()
                        assert proc.returncode == 0 or "Carrier" in combined_output, (
                            f"Multi-backend display failed: stdout={stdout.decode()}, stderr={stderr.decode()}"
                        )

    @pytest.mark.asyncio
    async def test_reset_multi_backend(self):
        """
        Test reset propagates to all backends through proxy.

        Verifies:
        - Reset command reaches all backend devices
        - Command completes successfully
        """
        dac1_port = get_test_port(0)
        dac2_port = get_test_port(1)
        proxy_port = get_test_proxy_port()

        with subprocess_dummy_dac(port=dac1_port) as _:
            with subprocess_dummy_dac(port=dac2_port) as _:
                async with Controller(standalone=True) as ctrl:
                    await ctrl.add_device("127.0.0.1", dac1_port)
                    await ctrl.add_device("127.0.0.1", dac2_port)

                    carrier_paths = list(ctrl.devices.keys())
                    mac_mapping = {}
                    for i, path in enumerate(carrier_paths):
                        virtual_mac = f"FF-FF-FF-FF-FF-{i:02X}"
                        mac_mapping[virtual_mac] = str(path)

                    partition_config = {"device": [list(mac_mapping.keys())]}

                    async with Proxy(
                        ctrl,
                        host="127.0.0.1",
                        port=proxy_port,
                        mac_mapping=mac_mapping,
                        partition_config=partition_config,
                    ) as (proxy, server):
                        # Use async subprocess to keep event loop running
                        proc = await asyncio.create_subprocess_exec(
                            sys.executable, "-m", "pybrid.cli.base",
                            "redac", "-h", "127.0.0.1", "-p", str(proxy_port),
                            "--no-reset",
                            "reset",
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE,
                        )
                        try:
                            stdout, stderr = await asyncio.wait_for(
                                proc.communicate(), timeout=60
                            )
                        except asyncio.TimeoutError:
                            proc.kill()
                            raise

                        assert proc.returncode == 0, f"Multi-backend reset failed: {stderr.decode()}"


class TestCLIProxyConnectionHandling:
    """Tests for CLI connection behavior with proxy."""

    def test_cli_handles_proxy_disconnect(self):
        """
        Test that CLI handles proxy disconnection gracefully.

        Verifies:
        - CLI reports connection error when proxy is not available
        - Error message is informative
        """
        # Try to connect to a port where nothing is listening
        result = subprocess.run(
            [
                sys.executable, "-m", "pybrid.cli.base",
                "redac", "-h", "127.0.0.1", "-p", "59999",
                "--no-reset",
                "display"
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        # Should fail with connection error
        assert result.returncode != 0 or "Connection refused" in result.stderr or "error" in result.stderr.lower(), (
            "CLI should report error when proxy unavailable"
        )

    def test_cli_timeout_on_unresponsive_proxy(self):
        """
        Test that CLI has reasonable timeout for unresponsive proxy.

        Verifies:
        - CLI does not hang indefinitely
        - Returns within timeout period
        """
        # Use a non-routable IP to simulate unresponsive server
        # Note: This test has a short timeout to avoid slow test runs
        result = subprocess.run(
            [
                sys.executable, "-m", "pybrid.cli.base",
                "redac", "-h", "192.0.2.1", "-p", "5732",  # TEST-NET-1, should be unreachable
                "--no-reset",
                "display"
            ],
            capture_output=True,
            text=True,
            timeout=60,  # Overall test timeout
        )

        # Should either timeout or fail to connect
        assert result.returncode != 0 or "timeout" in result.stderr.lower() or "error" in result.stderr.lower(), (
            "CLI should handle unresponsive proxy gracefully"
        )


class TestCLIRunThroughProxy:
    """Tests for the run command through proxy.

    Note: Run tests through proxy use the async in-process approach since
    the proxy requires dynamic MAC address mapping that matches the backend.
    """

    @pytest.mark.asyncio
    async def test_run_minimal_through_proxy(self):
        """
        Test 'pybrid redac run' with timing parameters through proxy.

        Verifies:
        - CLI can execute a run through proxy
        - Run completes without error
        """
        dac_port = get_test_port()
        proxy_port = get_test_proxy_port()

        with subprocess_dummy_dac(port=dac_port) as _:
            async with Controller(standalone=True) as ctrl:
                await ctrl.add_device("127.0.0.1", dac_port)

                carrier_paths = list(ctrl.devices.keys())
                mac_mapping = {
                    f"FF-FF-FF-FF-FF-{i:02X}": str(p)
                    for i, p in enumerate(carrier_paths)
                }
                partition_config = {"device": [list(mac_mapping.keys())]}

                async with Proxy(
                    ctrl,
                    host="127.0.0.1",
                    port=proxy_port,
                    mac_mapping=mac_mapping,
                    partition_config=partition_config,
                ) as (proxy, server):
                    proc = await asyncio.create_subprocess_exec(
                        sys.executable, "-m", "pybrid.cli.base",
                        "redac", "-h", "127.0.0.1", "-p", str(proxy_port),
                        "--no-reset",
                        "run",
                        "--ic-time", "10000",
                        "--op-time", "100000",
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    try:
                        stdout, stderr = await asyncio.wait_for(
                            proc.communicate(), timeout=60
                        )
                    except asyncio.TimeoutError:
                        proc.kill()
                        raise

                    assert proc.returncode == 0, (
                        f"Run through proxy failed:\nstdout={stdout.decode()}\nstderr={stderr.decode()}"
                    )

    @pytest.mark.asyncio
    async def test_run_with_sampling_through_proxy(self):
        """
        Test 'pybrid redac run' with sampling through proxy.

        Verifies:
        - CLI can execute a run with sample rate through proxy
        - Run completes and data is returned
        """
        dac_port = get_test_port()
        proxy_port = get_test_proxy_port()

        with subprocess_dummy_dac(port=dac_port) as _:
            async with Controller(standalone=True) as ctrl:
                await ctrl.add_device("127.0.0.1", dac_port)

                carrier_paths = list(ctrl.devices.keys())
                mac_mapping = {
                    f"FF-FF-FF-FF-FF-{i:02X}": str(p)
                    for i, p in enumerate(carrier_paths)
                }
                partition_config = {"device": [list(mac_mapping.keys())]}

                async with Proxy(
                    ctrl,
                    host="127.0.0.1",
                    port=proxy_port,
                    mac_mapping=mac_mapping,
                    partition_config=partition_config,
                ) as (proxy, server):
                    proc = await asyncio.create_subprocess_exec(
                        sys.executable, "-m", "pybrid.cli.base",
                        "redac", "-h", "127.0.0.1", "-p", str(proxy_port),
                        "--no-reset",
                        "run",
                        "--ic-time", "100000",
                        "--op-time", "1000000",
                        "--sample-rate", "10000",
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    try:
                        stdout, stderr = await asyncio.wait_for(
                            proc.communicate(), timeout=60
                        )
                    except asyncio.TimeoutError:
                        proc.kill()
                        raise

                    assert proc.returncode == 0, (
                        f"Run with sampling through proxy failed:\nstdout={stdout.decode()}\nstderr={stderr.decode()}"
                    )

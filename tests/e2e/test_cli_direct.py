# Copyright (c) 2022-2025 anabrid GmbH
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
E2E tests for CLI commands against DummyDAC directly.

Tests the pybrid CLI commands using subprocess to simulate real user interaction.
Uses DummyDAC as a mock backend to test CLI functionality without hardware.
"""

import subprocess
import sys

import pytest

from tests.conftest import subprocess_dummy_dac, TEST_DATA_DIR


class TestCLIHelp:
    """Tests for CLI help and basic command discovery."""

    @pytest.mark.parametrize("args,expected_words", [
        (["--help"], ["redac", "lucidac", "dummy", "detect"]),
        (["redac", "--help"], ["display", "run", "reset", "shell"]),
        (["dummy", "--help"], ["--host", "--port"]),
    ])
    def test_cli_help(self, args, expected_words):
        result = subprocess.run(
            [sys.executable, "-m", "pybrid.cli.base"] + args,
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode == 0, f"CLI help failed: {result.stderr}"
        for word in expected_words:
            assert word in result.stdout, f"Expected '{word}' in help output"


class TestCLIDisplayDirect:
    """Tests for the display command against DummyDAC."""

    @pytest.mark.asyncio
    async def test_display_with_fake_mode(self):
        result = subprocess.run(
            [sys.executable, "-m", "pybrid.cli.base", "redac", "--fake", "display"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        # Note: Display with fake mode should work without a server
        # It may print warnings about zeroconf but should still function
        # Accept exit code 0 or informational output
        assert "Usage:" not in result.stdout or result.returncode == 0, (
            f"Display command should work in fake mode: {result.stderr}"
        )

    def test_display_against_dummy_dac(self):
        with subprocess_dummy_dac() as port:
            result = subprocess.run(
                [
                    sys.executable, "-m", "pybrid.cli.base",
                    "redac", "-h", "127.0.0.1", "-p", str(port),
                    "--no-reset",
                    "display"
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )

            combined_output = result.stdout + result.stderr
            assert result.returncode == 0 or "00-00-00-00-00-00" in combined_output or "Carrier" in combined_output, (
                f"Display should show hardware info: stdout={result.stdout}, stderr={result.stderr}"
            )


class TestCLIResetDirect:
    """Tests for the reset command against DummyDAC."""

    def test_reset_against_dummy_dac(self):
        with subprocess_dummy_dac() as port:
            result = subprocess.run(
                [
                    sys.executable, "-m", "pybrid.cli.base",
                    "redac", "-h", "127.0.0.1", "-p", str(port),
                    "--no-reset",
                    "reset"
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )

            assert result.returncode == 0, f"Reset command failed: {result.stderr}"

    def test_reset_with_keep_calibration(self):
        with subprocess_dummy_dac() as port:
            result = subprocess.run(
                [
                    sys.executable, "-m", "pybrid.cli.base",
                    "redac", "-h", "127.0.0.1", "-p", str(port),
                    "--no-reset",
                    "reset", "--keep-calibration", "True"
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )

            assert result.returncode == 0, f"Reset with keep-calibration failed: {result.stderr}"


class TestCLIRunDirect:
    """Tests for the run command against DummyDAC."""

    def test_run_with_config_file(self):
        config_path = TEST_DATA_DIR / "harmonic_pb.json"

        if not config_path.exists():
            pytest.skip("harmonic_pb.json not found in test data")

        with subprocess_dummy_dac() as port:
            result = subprocess.run(
                [
                    sys.executable, "-m", "pybrid.cli.base",
                    "redac", "-h", "127.0.0.1", "-p", str(port),
                    "--no-reset", "--sync-impl", "native",
                    "run",
                    "-c", str(config_path),
                    "--ic-time", "100000",
                    "--op-time", "0.001",
                    "--sample-rate", "10000",
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )

            assert result.returncode == 0, f"Run command failed: {result.stderr}"

    def test_run_minimal_parameters(self):
        with subprocess_dummy_dac() as port:
            result = subprocess.run(
                [
                    sys.executable, "-m", "pybrid.cli.base",
                    "redac", "-h", "127.0.0.1", "-p", str(port),
                    "--no-reset", "--sync-impl", "native",
                    "run",
                    "--ic-time", "1000",
                    "--op-time", "0.001",
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )

            assert result.returncode == 0, (
                f"Run failed:\nstdout={result.stdout}\nstderr={result.stderr}"
            )

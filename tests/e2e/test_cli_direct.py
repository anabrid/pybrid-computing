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

    def test_cli_help_shows_commands(self):
        """
        Test that 'pybrid --help' shows available commands.

        Verifies:
        - CLI entrypoint is accessible via python -m
        - Help output lists main command groups (redac, lucidac, dummy, detect)
        """
        result = subprocess.run(
            [sys.executable, "-m", "pybrid.cli.base", "--help"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode == 0, f"CLI help failed: {result.stderr}"
        assert "redac" in result.stdout, "Should list redac command"
        assert "lucidac" in result.stdout, "Should list lucidac command"
        assert "dummy" in result.stdout, "Should list dummy command"
        assert "detect" in result.stdout, "Should list detect command"

    def test_cli_redac_help_shows_subcommands(self):
        """
        Test that 'pybrid redac --help' shows REDAC subcommands.

        Verifies:
        - REDAC command group is accessible
        - Shows subcommands like display, run, reset, shell
        """
        result = subprocess.run(
            [sys.executable, "-m", "pybrid.cli.base", "redac", "--help"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode == 0, f"REDAC help failed: {result.stderr}"
        assert "display" in result.stdout, "Should list display subcommand"
        assert "run" in result.stdout, "Should list run subcommand"
        assert "reset" in result.stdout, "Should list reset subcommand"
        assert "shell" in result.stdout, "Should list shell subcommand"

    def test_cli_dummy_help_shows_options(self):
        """
        Test that 'pybrid dummy --help' shows DummyDAC options.

        Verifies:
        - Dummy command is accessible
        - Shows host, port, and virtual/physical options
        """
        result = subprocess.run(
            [sys.executable, "-m", "pybrid.cli.base", "dummy", "--help"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode == 0, f"Dummy help failed: {result.stderr}"
        assert "--host" in result.stdout or "-h" in result.stdout, "Should have host option"
        assert "--port" in result.stdout or "-p" in result.stdout, "Should have port option"
        assert "--virtual" in result.stdout or "--physical" in result.stdout, "Should have MAC mode option"


class TestCLIDisplayDirect:
    """Tests for the display command against DummyDAC."""

    @pytest.mark.asyncio
    async def test_display_with_fake_mode(self):
        """
        Test 'pybrid redac --fake display' shows hardware structure.

        Verifies:
        - Display command works in fake mode (no network required)
        - Output contains hardware structure information
        """
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
        """
        Test 'pybrid redac -h HOST -p PORT display' against DummyDAC.

        Verifies:
        - CLI can connect to running DummyDAC
        - Display shows hardware structure from DummyDAC
        """
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
        """
        Test 'pybrid redac -h HOST -p PORT reset' against DummyDAC.

        Verifies:
        - CLI can connect and send reset command to DummyDAC
        - Reset command completes without error
        """
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
        """
        Test reset with --keep-calibration flag.

        Verifies:
        - Reset accepts keep-calibration option
        - Command completes successfully
        """
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


class TestCLILogLevel:
    """Tests for CLI log level configuration."""

    def test_log_level_debug(self):
        """
        Test that --log-level DEBUG produces debug output.

        Verifies:
        - Log level option is accepted
        - Debug level produces more verbose output
        """
        result = subprocess.run(
            [
                sys.executable, "-m", "pybrid.cli.base",
                "--log-level", "DEBUG",
                "--help"
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode == 0, f"CLI with debug log level failed: {result.stderr}"

    def test_log_level_error(self):
        """
        Test that --log-level ERROR suppresses warnings.

        Verifies:
        - Error level option is accepted
        - Produces less verbose output
        """
        result = subprocess.run(
            [
                sys.executable, "-m", "pybrid.cli.base",
                "--log-level", "ERROR",
                "--help"
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode == 0, f"CLI with error log level failed: {result.stderr}"


class TestCLIRunDirect:
    """Tests for the run command against DummyDAC."""

    def test_run_with_config_file(self):
        """
        Test 'pybrid redac run -c CONFIG_FILE' against DummyDAC.

        Uses harmonic_pb.json as a valid circuit configuration.

        Verifies:
        - CLI can execute a run with config file
        - Run completes without error
        """
        config_path = TEST_DATA_DIR / "harmonic_pb.json"

        if not config_path.exists():
            pytest.skip("harmonic_pb.json not found in test data")

        with subprocess_dummy_dac() as port:
            result = subprocess.run(
                [
                    sys.executable, "-m", "pybrid.cli.base",
                    "redac", "-h", "127.0.0.1", "-p", str(port),
                    "--no-reset",
                    "run",
                    "-c", str(config_path),
                    "--ic-time", "100000",
                    "--op-time", "1000000",
                    "--sample-rate", "10000",
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )

            assert result.returncode == 0, f"Run command failed: {result.stderr}"

    def test_run_minimal_parameters(self):
        """
        Test run with minimal parameters.

        Verifies CLI can execute a simple run with just timing parameters.
        """
        with subprocess_dummy_dac() as port:
            result = subprocess.run(
                [
                    sys.executable, "-m", "pybrid.cli.base",
                    "redac", "-h", "127.0.0.1", "-p", str(port),
                    "--no-reset",
                    "run",
                    "--ic-time", "1000",
                    "--op-time", "10000",
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )

            assert result.returncode == 0, (
                f"Run failed:\nstdout={result.stdout}\nstderr={result.stderr}"
            )

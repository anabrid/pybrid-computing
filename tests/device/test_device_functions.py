# Copyright (c) 2022-2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
Numerical accuracy validation tests for analog computation.

These tests verify that the analog computer produces results
within acceptable accuracy tolerances for known mathematical
problems (e.g., harmonic oscillator).

Environment Variables:
    TEST_LUCIDAC_ENDPOINT: tcp://host:port for LUCIDAC connection
    TEST_REDAC_ENDPOINT: tcp://host:port for REDAC connection
    TEST_SIMULATOR_ENDPOINT: tcp://host:port for Simulator connection
"""

import asyncio
import json
import math
from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest

from pybrid.base.proto.io import ProtoIO
from pybrid.redac.controller import Controller
from pybrid.redac.run import Run, RunConfig, DAQConfig, RunState


@pytest.fixture
def harmonic_pb_config():
    """
    Load harmonic oscillator config in protobuf JSON format.

    Returns:
        pb.File containing the harmonic oscillator configuration loaded from
        the test data directory and parsed into protobuf format.
    """
    config_path = Path(__file__).parent.parent / "data" / "harmonic_pb.json"
    with open(config_path) as f:
        json_config = json.load(f)
    return ProtoIO.json_to_pbfile(json_config)


@pytest.mark.device
class TestHarmonicOscillatorOnDevice:
    """
    Tests basic properties of the samples generated for a harmonic oscillator circuit on analog devices.
    This is not a hardcore test for accuracy and should ONLY be understood as basic test
    that the device basic functions work as intended. 

    If either of those tests go wrong, there is a MASSIVE issue within the codebase,
    device or configuration!
    """

    async def test_harmonic_amplitude(self, any_device_endpoint, harmonic_pb_config):
        """Amplitude tolerance is wide to accommodate the energy increase real devices exhibit."""
        host, port, device_type = any_device_endpoint

        async with Controller() as ctrl:
            await ctrl.add_device(host, port)

            # Get device paths for config addressing
            device_paths = list(ctrl.devices.keys())
            if not device_paths:
                pytest.skip("No devices available")

            await ctrl.set_module(harmonic_pb_config.module)

            # Create run with DAQ configuration
            run = Run(
                id_=uuid4(),
                config=RunConfig(
                    ic_time=100_000,       # 100us IC time
                    op_time=10_000_000,    # 10ms OP time (several oscillation periods)
                ),
                daq=DAQConfig(
                    num_channels=2,        # Sample x and v
                    sample_rate=25_000,   # 10kHz
                    sample_op=True,
                    sample_op_end=True,
                ),
            )

            # Start the run
            run_state = await ctrl.start_run(run)

            # Wait for completion
            try:
                async with asyncio.timeout(30.0):
                    await run_state.wait_all(RunState.DONE)
            except asyncio.TimeoutError:
                pytest.fail("Harmonic oscillator run timed out")

            # Check if we collected data
            if not run.data:
                pytest.fail("No DAQ data collected - circuit configuration failed")

            # Verify data was collected and check amplitude preservation
            for channel, values in run.data.items():

                if len(values) > 0:
                    data_array = np.array(values)

                    # Basic sanity checks
                    assert not np.all(np.isnan(data_array)), (
                        f"Channel {channel} should not have all NaN values"
                    )

                    # For harmonic oscillator, check amplitude is roughly preserved
                    # The initial condition v(0) = -0.42 should result in amplitude ~0.42
                    max_amplitude = np.max(data_array)
                    min_amplitude = np.min(data_array)
                    assert max_amplitude > 0.4 and max_amplitude < 0.5, (
                        f"Maximum amplitude {max_amplitude} not in [0.4, 0.5]"
                    )
                    assert min_amplitude > -0.5 and min_amplitude < -0.4, (
                        f"Minimum amplitude {min_amplitude} not in [-0.5, -0.4]"
                    )
                    break

    async def test_harmonic_frequency(self, any_device_endpoint, harmonic_pb_config):
        """Expected frequency is k/(2*pi) ~ 1592 Hz with 5% tolerance for analog variation."""
        host, port, device_type = any_device_endpoint

        async with Controller() as ctrl:
            await ctrl.add_device(host, port)

            # Get device paths for config addressing
            device_paths = list(ctrl.devices.keys())
            if not device_paths:
                pytest.skip("No devices available")

            await ctrl.set_module(harmonic_pb_config.module)

            # Create run for frequency measurement
            run = Run(
                id_=uuid4(),
                config=RunConfig(
                    ic_time=100_000,
                    op_time=50_000_000,  # 50ms - enough for frequency analysis
                ),
                daq=DAQConfig(
                    num_channels=1,
                    sample_rate=10_000,
                    sample_op=True,
                ),
            )

            run_state = await ctrl.start_run(run)

            try:
                async with asyncio.timeout(60.0):
                    await run_state.wait_all(RunState.DONE)
            except asyncio.TimeoutError:
                pytest.fail("Frequency measurement run timed out")

            # Analyze collected data for frequency
            if not run.data:
                pytest.fail("No DAQ data collected for frequency analysis")

            for channel, values in run.data.items():
                if len(values) >= 100:  # Need enough samples for FFT
                    data_array = np.array(values)

                    # Perform FFT
                    fft_result = np.fft.fft(data_array)
                    freqs = np.fft.fftfreq(len(data_array),
                                           d=1.0/run.daq.sample_rate)

                    # Find dominant frequency
                    positive_freqs = freqs[:len(freqs)//2]
                    magnitudes = np.abs(fft_result[:len(freqs)//2])

                    # Skip DC component
                    if len(magnitudes) > 1:
                        peak_idx = np.argmax(magnitudes[1:]) + 1
                        dominant_freq = positive_freqs[peak_idx]

                        # For the harmonic oscillator with k=10000 (time constant),
                        # the expected frequency is around k/(2*pi) = ~1592 Hz
                        # Allow some tolerance due to analog component variations
                        expected_freq = 10000 / (2 * math.pi)
                        freq_tolerance = 0.05  # 5% tolerance

                        assert dominant_freq > 0, (
                            "Dominant frequency should be positive"
                        )
                        assert abs(dominant_freq - expected_freq) / expected_freq < freq_tolerance, (
                            f"Measured frequency {dominant_freq:.1f} Hz differs from "
                            f"expected {expected_freq:.1f} Hz by more than {freq_tolerance*100}%"
                        )
                    break

    async def test_data_collection_infrastructure(
        self, any_device_endpoint, harmonic_pb_config
    ):
        host, port, device_type = any_device_endpoint

        # DAQ configuration parameters
        sample_rate = 10_000  # 10 kHz
        op_time_us = 50_000_000  # 50 ms

        # Calculate expected number of samples (with tolerance for timing)
        expected_samples = int(op_time_us * sample_rate / 1_000_000_000)
        sample_tolerance = 0.1  # Allow 10% tolerance for timing variations

        async with Controller() as ctrl:
            await ctrl.add_device(host, port)

            # Get device paths for config addressing
            device_paths = list(ctrl.devices.keys())
            if not device_paths:
                pytest.skip("No devices available")

            # Map virtual addresses to physical only for LUCIDAC
            # Simulator and REDAC use virtual addresses directly
            if device_type == "lucidac":
                pb_file = Addressing.virtual_to_physical(ctrl.computer, harmonic_pb_config)
            else:
                pb_file = harmonic_pb_config

            # Apply the circuit configuration to the device
            await ctrl.set_module(pb_file.module)

            # Configure a run with explicit DAQ settings
            run = Run(
                id_=uuid4(),
                config=RunConfig(
                    ic_time=100_000,
                    op_time=op_time_us,
                ),
                daq=DAQConfig(
                    num_channels=1,
                    sample_rate=sample_rate,
                    sample_op=True,
                ),
            )

            run_state = await ctrl.start_run(run)

            try:
                async with asyncio.timeout(30.0):
                    await run_state.wait_all(RunState.DONE)
            except asyncio.TimeoutError:
                pytest.fail("Data collection run timed out")

            # Verify run completed
            assert run.state == RunState.DONE, (
                f"Run should be in DONE state, got {run.state}"
            )

            # Verify data was collected
            assert hasattr(run, 'data'), "Run should have data attribute"
            assert isinstance(run.data, dict), "Run.data should be a dictionary"
            assert len(run.data) > 0, "No DAQ data collected - circuit may have failed"

            # Verify number of channels matches requested
            actual_channels = len(run.data)
            assert actual_channels == 1, (
                f"Expected 1 channel, got {actual_channels}"
            )

            # Verify sample count is roughly as expected for each channel
            for channel, values in run.data.items():
                actual_samples = len(values)
                min_expected = int(expected_samples * (1 - sample_tolerance))
                max_expected = int(expected_samples * (1 + sample_tolerance))

                assert actual_samples >= min_expected, (
                    f"Channel {channel}: got {actual_samples} samples, "
                    f"expected at least {min_expected} (expected ~{expected_samples})"
                )
                assert actual_samples <= max_expected, (
                    f"Channel {channel}: got {actual_samples} samples, "
                    f"expected at most {max_expected} (expected ~{expected_samples})"
                )

            # Final values dictionary should exist
            assert hasattr(run, 'final_values'), (
                "Run should have final_values attribute"
            )
            assert isinstance(run.final_values, dict), (
                "Run.final_values should be a dictionary"
            )

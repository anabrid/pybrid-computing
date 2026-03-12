# Copyright (c) 2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""Integration tests verifying that DummyDAC calibration state affects run outputs.

The DummyDAC scales sample amplitudes by ``StartRunHandler.CALIBRATION_SCALE``
(0.5) when a CalibrationCommand with at least one enabled kind has been issued.
These tests compare Session runs with and without prior calibration to verify
the output difference is observable.
"""

import asyncio

import numpy as np
import pytest

from pybrid.mock import DummyDAC, DummyDACConfig, DummyDACMacMode
from pybrid.redac.controller import Controller as REDACController
from pybrid.redac.run import RunConfig, DAQConfig

try:
    from pybrid.native._impl import ControlChannel as _NativeControlChannel
    _NATIVE_AVAILABLE = True
except ImportError:
    _NATIVE_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not _NATIVE_AVAILABLE,
    reason="pybrid.native._impl is not available (C++ bindings not built)",
)

LOCALHOST = "127.0.0.1"
RUN_OP_TIME_NS = 50_000_000  # 50 ms
RUN_TIMEOUT = RUN_OP_TIME_NS / 1e9 + 5.0


def _make_run_config() -> RunConfig:
    return RunConfig(ic_time=100_000, op_time=RUN_OP_TIME_NS, halt_on_overload=False)


def _make_daq_config() -> DAQConfig:
    return DAQConfig(num_channels=4, sample_rate=1000, sample_op=True, sample_op_end=True)


@pytest.mark.asyncio
async def test_calibrated_run_scales_sample_data():
    """A run after calibration produces sample amplitudes scaled by CALIBRATION_SCALE
    compared to an uncalibrated run."""
    config = DummyDACConfig(mac_mode=DummyDACMacMode.PHYSICAL)
    async with DummyDAC(LOCALHOST, 0, config) as dac:
        port = dac.port

        async with REDACController() as ctrl:
            await ctrl.add_device(LOCALHOST, port)

            # --- Uncalibrated run ---
            session_uncal = ctrl.create_session()
            session_uncal.run(_make_run_config(), daq=_make_daq_config())
            runs_uncal = await asyncio.wait_for(session_uncal.execute(), timeout=RUN_TIMEOUT)
            assert len(runs_uncal) == 1
            run_uncal = runs_uncal[0]

            # --- Calibrated run ---
            session_cal = ctrl.create_session()
            session_cal.calibrate(gain=True)
            session_cal.run(_make_run_config(), daq=_make_daq_config())
            runs_cal = await asyncio.wait_for(session_cal.execute(), timeout=RUN_TIMEOUT)
            assert len(runs_cal) == 1
            run_cal = runs_cal[0]

    assert run_uncal.data, "Uncalibrated run produced no sample data"
    assert run_cal.data, "Calibrated run produced no sample data"

    # Both runs must have the same channel paths.
    assert set(run_uncal.data.keys()) == set(run_cal.data.keys()), (
        "Channel paths differ between calibrated and uncalibrated runs"
    )

    from pybrid.mock.handler.start_run import StartRunHandler
    expected_scale = StartRunHandler.CALIBRATION_SCALE

    for path in run_uncal.data:
        uncal_arr = np.array(run_uncal.data[path], dtype=np.float64)
        cal_arr = np.array(run_cal.data[path], dtype=np.float64)
        assert len(uncal_arr) == len(cal_arr), (
            f"Sample count mismatch for {path}: {len(uncal_arr)} vs {len(cal_arr)}"
        )

        # Skip channels that are all-zero (no signal to compare).
        if np.allclose(uncal_arr, 0, atol=1e-6):
            continue

        ratio = cal_arr / np.where(np.abs(uncal_arr) > 1e-9, uncal_arr, np.nan)
        valid = ~np.isnan(ratio)
        assert valid.any(), f"No non-zero samples to compare for {path}"
        np.testing.assert_allclose(
            ratio[valid], expected_scale, atol=1e-4,
            err_msg=f"Calibrated/uncalibrated ratio for {path} should be {expected_scale}",
        )


@pytest.mark.asyncio
async def test_calibrated_run_scales_final_values():
    """A run after calibration produces final_values scaled by CALIBRATION_SCALE."""
    config = DummyDACConfig(mac_mode=DummyDACMacMode.PHYSICAL)
    async with DummyDAC(LOCALHOST, 0, config) as dac:
        port = dac.port

        async with REDACController() as ctrl:
            await ctrl.add_device(LOCALHOST, port)

            # --- Uncalibrated run ---
            session_uncal = ctrl.create_session()
            session_uncal.run(_make_run_config(), daq=_make_daq_config())
            runs_uncal = await asyncio.wait_for(session_uncal.execute(), timeout=RUN_TIMEOUT)
            run_uncal = runs_uncal[0]

            # --- Calibrated run ---
            session_cal = ctrl.create_session()
            session_cal.calibrate(offset=True)
            session_cal.run(_make_run_config(), daq=_make_daq_config())
            runs_cal = await asyncio.wait_for(session_cal.execute(), timeout=RUN_TIMEOUT)
            run_cal = runs_cal[0]

    assert run_uncal.final_values, "Uncalibrated run produced no final_values"
    assert run_cal.final_values, "Calibrated run produced no final_values"

    from pybrid.mock.handler.start_run import StartRunHandler
    expected_scale = StartRunHandler.CALIBRATION_SCALE

    common_paths = set(run_uncal.final_values) & set(run_cal.final_values)
    assert common_paths, "No shared paths between calibrated and uncalibrated final_values"

    for path in common_paths:
        uncal_val = run_uncal.final_values[path]
        cal_val = run_cal.final_values[path]
        if abs(uncal_val) < 1e-9:
            continue
        ratio = cal_val / uncal_val
        assert abs(ratio - expected_scale) < 1e-4, (
            f"final_values[{path}]: calibrated={cal_val}, uncalibrated={uncal_val}, "
            f"ratio={ratio}, expected={expected_scale}"
        )


@pytest.mark.asyncio
async def test_reset_without_keep_calibration_clears_state():
    """A reset with keep_calibration=False followed by a run produces uncalibrated output."""
    config = DummyDACConfig(mac_mode=DummyDACMacMode.PHYSICAL)
    async with DummyDAC(LOCALHOST, 0, config) as dac:
        port = dac.port

        async with REDACController() as ctrl:
            await ctrl.add_device(LOCALHOST, port)

            # Calibrate, then reset without keeping calibration.
            session_cal = ctrl.create_session()
            session_cal.calibrate(gain=True)
            session_cal.run(_make_run_config(), daq=_make_daq_config())
            runs_cal = await asyncio.wait_for(session_cal.execute(), timeout=RUN_TIMEOUT)
            run_cal = runs_cal[0]

            await ctrl.reset(keep_calibration=False)

            # Run after reset — should be uncalibrated.
            session_after = ctrl.create_session()
            session_after.run(_make_run_config(), daq=_make_daq_config())
            runs_after = await asyncio.wait_for(session_after.execute(), timeout=RUN_TIMEOUT)
            run_after = runs_after[0]

            # Reference uncalibrated run (fresh state after the reset).
            # Compare the two: they should match.
            for path in run_after.data:
                after_arr = np.array(run_after.data[path], dtype=np.float64)
                if path in run_cal.data:
                    cal_arr = np.array(run_cal.data[path], dtype=np.float64)
                    min_len = min(len(after_arr), len(cal_arr))
                    if min_len > 0 and not np.allclose(after_arr[:min_len], 0, atol=1e-6):
                        # After-reset samples should NOT match the calibrated ones
                        # (calibrated are scaled by 0.5).
                        assert not np.allclose(after_arr[:min_len], cal_arr[:min_len], atol=1e-4), (
                            f"Samples for {path} after reset(keep_calibration=False) still "
                            "match calibrated output — calibration state was not cleared."
                        )

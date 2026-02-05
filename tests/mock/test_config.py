# Copyright (c) 2022-2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""Tests for the DummyDAC configuration module."""

from pybrid.mock import DummyDACConfig, DummyDACErrorStage, DummyDACMacMode


def test_config_imports():
    """Verify module imports work correctly."""
    assert DummyDACErrorStage.NONE is not None
    assert DummyDACMacMode.VIRTUAL is not None


def test_config_defaults():
    """Verify default configuration values."""
    config = DummyDACConfig()
    assert config.mac_mode == DummyDACMacMode.VIRTUAL
    assert config.accept_udp_streaming == True
    assert config.error_stage == DummyDACErrorStage.NONE
    assert config.error_message is None


def test_config_custom_values():
    """Verify custom configuration values."""
    config = DummyDACConfig(
        mac_mode=DummyDACMacMode.PHYSICAL,
        accept_udp_streaming=False,
        error_stage=DummyDACErrorStage.AT_CONFIGURE,
        error_message="Test error"
    )
    assert config.mac_mode == DummyDACMacMode.PHYSICAL
    assert config.accept_udp_streaming == False
    assert config.error_stage == DummyDACErrorStage.AT_CONFIGURE
    assert config.error_message == "Test error"


def test_error_stage_enum_values():
    """Verify all error stage enum values exist."""
    expected = ['NONE', 'AT_CONFIGURE', 'AT_START_RUN', 'AT_EXTRACT',
                'DURING_RUN', 'DROP_TAKEOFF_STATE', 'DROP_DONE_STATE', 'FEWER_SAMPLES']
    for name in expected:
        assert hasattr(DummyDACErrorStage, name)

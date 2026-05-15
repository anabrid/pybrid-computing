# Copyright (c) 2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""Tests for AdcProbeValidator and its integration into the serialization pipeline."""

import pytest

from pybrid.base.hybrid.validators import ConfigValidator
from pybrid.base.result import Result
from pybrid.redac.blocks import CBlock, IBlock, UBlock
from pybrid.redac.carrier import ADCChannel, Carrier
from pybrid.redac.cluster import Cluster
from pybrid.redac.computer import REDAC
from pybrid.redac.entities import Loc, Path
from pybrid.redac.protocol.validators import AdcProbeValidator


def _make_carrier(mac: str, adc_channels: list) -> Carrier:
    """Build a minimal Carrier with the given ADC config."""
    carrier_path = Path.parse(mac)
    cluster_path = carrier_path / "0"
    cluster = Cluster(
        path=cluster_path,
        location=Loc.new_cluster(0, 0, 0),
        ublock=UBlock(path=cluster_path / "U"),
        cblock=CBlock(path=cluster_path / "C"),
        iblock=IBlock(path=cluster_path / "I"),
        shblock=None,
    )
    return Carrier(
        path=carrier_path,
        location=Loc.new_carrier(0, 0),
        clusters=[cluster],
        tblock=None,
        adc_config=adc_channels,
    )


def _make_redac(*carriers: Carrier) -> REDAC:
    return REDAC(entities=list(carriers))


class TestAdcProbeValidator:

    def test_valid_contiguous_probes(self):
        carrier = _make_carrier(
            "AA-BB-CC-DD-EE-FF",
            [
                ADCChannel(index=0, probe=0),
                ADCChannel(index=1, probe=1),
                ADCChannel(index=2, probe=2),
            ],
        )
        result = AdcProbeValidator().validate(_make_redac(carrier))
        assert result.ok

    def test_missing_probe_when_any_set(self):
        """Once any probe is assigned, all channels must have probes."""
        carrier = _make_carrier(
            "AA-BB-CC-DD-EE-FF",
            [
                ADCChannel(index=0, probe=0),
                ADCChannel(index=1, probe=None),
            ],
        )
        result = AdcProbeValidator().validate(_make_redac(carrier))
        assert not result.ok
        assert "no probe assignment" in result.error

    def test_non_contiguous_probes(self):
        carrier = _make_carrier(
            "AA-BB-CC-DD-EE-FF",
            [
                ADCChannel(index=0, probe=0),
                ADCChannel(index=1, probe=2),
            ],
        )
        result = AdcProbeValidator().validate(_make_redac(carrier))
        assert not result.ok
        assert "not contiguous" in result.error

    def test_non_zero_start(self):
        carrier = _make_carrier(
            "AA-BB-CC-DD-EE-FF",
            [
                ADCChannel(index=0, probe=1),
                ADCChannel(index=1, probe=2),
            ],
        )
        result = AdcProbeValidator().validate(_make_redac(carrier))
        assert not result.ok
        assert "not contiguous" in result.error

    def test_empty_adc_config_passes(self):
        carrier = _make_carrier("AA-BB-CC-DD-EE-FF", [])
        result = AdcProbeValidator().validate(_make_redac(carrier))
        assert result.ok

    def test_multi_carrier_valid(self):
        carrier_a = _make_carrier(
            "AA-BB-CC-DD-EE-01",
            [
                ADCChannel(index=0, probe=0),
                ADCChannel(index=1, probe=1),
            ],
        )
        carrier_b = _make_carrier(
            "AA-BB-CC-DD-EE-02",
            [
                ADCChannel(index=0, probe=2),
                ADCChannel(index=1, probe=3),
            ],
        )
        result = AdcProbeValidator().validate(_make_redac(carrier_a, carrier_b))
        assert result.ok

    def test_duplicate_across_carriers(self):
        carrier_a = _make_carrier(
            "AA-BB-CC-DD-EE-01",
            [
                ADCChannel(index=0, probe=0),
            ],
        )
        carrier_b = _make_carrier(
            "AA-BB-CC-DD-EE-02",
            [
                ADCChannel(index=0, probe=0),
            ],
        )
        result = AdcProbeValidator().validate(_make_redac(carrier_a, carrier_b))
        assert not result.ok
        assert "Duplicate" in result.error

    def test_none_entries_in_adc_config_skipped(self):
        """None entries (free slots) in adc_config should be ignored."""
        carrier = _make_carrier(
            "AA-BB-CC-DD-EE-FF",
            [
                None,
                ADCChannel(index=1, probe=0),
                None,
                ADCChannel(index=3, probe=1),
            ],
        )
        result = AdcProbeValidator().validate(_make_redac(carrier))
        assert result.ok

    def test_mixed_errors_reported_together(self):
        """A config with both missing probes AND duplicates surfaces both errors."""
        carrier_a = _make_carrier(
            "AA-BB-CC-DD-EE-01",
            [
                ADCChannel(index=0, probe=0),
                ADCChannel(index=1, probe=None),
            ],
        )
        carrier_b = _make_carrier(
            "AA-BB-CC-DD-EE-02",
            [
                ADCChannel(index=0, probe=0),
            ],
        )
        result = AdcProbeValidator().validate(_make_redac(carrier_a, carrier_b))
        assert not result.ok
        assert "no probe assignment" in result.error
        assert "Duplicate" in result.error


class TestSerializerCollectsAllErrors:

    def test_serializer_raises_on_invalid_probes(self):
        """Serializer runs AdcProbeValidator: mixed probed/unprobed raises."""
        from pybrid.redac.protocol.serializer import REDACSerializer

        carrier = _make_carrier(
            "AA-BB-CC-DD-EE-FF",
            [
                ADCChannel(index=0, probe=0),
                ADCChannel(index=1, probe=None),
            ],
        )
        computer = _make_redac(carrier)
        serializer = REDACSerializer()

        with pytest.raises(ValueError, match="no probe assignment"):
            serializer.serialize(computer)

    def test_serializer_collects_from_multiple_validators(self):
        """When multiple validators fail, the exception message contains all errors."""

        class FailingValidatorA(ConfigValidator):
            def validate(self, computer):
                return Result.failure("error from A")

        class FailingValidatorB(ConfigValidator):
            def validate(self, computer):
                return Result.failure("error from B")

        carrier = _make_carrier("AA-BB-CC-DD-EE-FF", [])
        computer = _make_redac(carrier)

        from pybrid.redac.protocol.serializer import REDACSerializer

        serializer = REDACSerializer()
        serializer.validators = [FailingValidatorA(), FailingValidatorB()]

        with pytest.raises(ValueError, match="2 error") as exc_info:
            serializer.serialize(computer)

        msg = str(exc_info.value)
        assert "error from A" in msg
        assert "error from B" in msg

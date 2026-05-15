# Copyright (c) 2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

from pybrid.base.hybrid.computer import AnalogComputer
from pybrid.base.hybrid.validators import ConfigValidator
from pybrid.base.result import Result


class AdcProbeValidator(ConfigValidator):
    """Validates that ADC probe indices are contiguous across all carriers."""

    def validate(self, computer: AnalogComputer) -> Result:
        channels = []
        for carrier in computer.carriers:
            for adc_channel in carrier.adc_config:
                if adc_channel is not None:
                    channels.append(adc_channel)

        if not channels:
            return Result.success()

        probed = [ch for ch in channels if ch.probe is not None]
        unprobed = [ch for ch in channels if ch.probe is None]

        # If no channel has a probe, skip validation (backward compat).
        if not probed:
            return Result.success()

        errors: list[str] = []

        # Once any probe is set, all must be set.
        if unprobed:
            errors.append(
                f"ADC channel (index={unprobed[0].index}) has no probe assignment. "
                f"All active ADC channels must have a probe index when any probe is set."
            )

        probes = [ch.probe for ch in channels if ch.probe is not None]
        probe_set = set(probes)

        if -1 in probe_set:
            errors.append("All ADC channels require probes.")

        if len(probe_set) != len(probes):
            errors.append(
                f"Duplicate probe indices found: {sorted(probes)}. "
                f"Probe indices must be globally unique across all carriers."
            )

        if not errors:
            expected = set(range(len(channels)))
            if probe_set != expected:
                errors.append(
                    f"Probe indices {sorted(probe_set)} are not contiguous from 0. " f"Expected {sorted(expected)}."
                )

        if errors:
            return Result.failure("\n".join(errors))
        return Result.success()


__all__ = ["AdcProbeValidator"]

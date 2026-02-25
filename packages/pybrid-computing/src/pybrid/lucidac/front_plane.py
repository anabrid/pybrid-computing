# Copyright (c) 2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
Canonical module for the LUCIDAC front plane (FP) entity.

The front plane provides a configurable signal generator and LED controls
on LUCIDAC hardware.  Previously this class was named ``FrontPanel``; the
rename to ``FrontPlane`` aligns with anabrid firmware terminology.

Backward-compatible imports via ``pybrid.lucidac.front_panel`` continue
to work but emit a :class:`DeprecationWarning`.
"""

import typing
from dataclasses import field, dataclass
from enum import Enum

from pybrid.base.proto import main_pb2 as pb
from pybrid.redac.entities import Entity, EntityType, EntityClass

class WaveForm(int, Enum):
    """Output mode for the LUCIDAC's signal generator."""
    #: Output sine signal ONLY
    SINE = 0
    #: Output sine and rect signals at the same time
    SINE_AND_SQUARE = 1
    #: Output ONLY triangle signal from the sine plug
    TRIANGLE = 2

@dataclass
class SignalGenerator:
    """
    Settings for the signal generator on LUCIDAC's front plane.

    The signal generator can either put out a sine and square ("rectangle"/"rect")
    signal OR a triangle signal. At the same time, via the aux plugs, two
    (inverted) constants can be set.
    """
    #: Frequency in Hz for the Sine/Triangle
    frequency: float = field(default=0)

    #: The signal's phase
    phase: float = field(default=0)

    #: Sets the kind of signal generated
    wave_form: WaveForm = field(default=WaveForm.SINE_AND_SQUARE)

    #: Amplitude for the sine/triangle signal
    amplitude: float = field(default=0)

    #: Upper value for the rect signal (in [-1,1])
    square_voltage_low: float = field(default=0)

    #: Lower value for the rect signal (in [-1,1])
    square_voltage_high: float = field(default=0)

    #: Vertical offset of all signals (in [-1,1])
    offset: float = field(default=0)

    #: Turns generator on/off
    sleep: bool = field(default=True)

    #: Set constant outputs on AUX0, Aux1
    dac_outputs: typing.List[float] = field(default_factory=lambda: [0.0, 0.0])

@EntityType.register(EntityClass.FRONTPANEL)
@dataclass
class FrontPlane(Entity):
    """
    Class modelling a LUCIDAC front plane with (configurable) LEDs and Signal Generator.

    Renamed from ``FrontPanel`` to ``FrontPlane`` to align with firmware terminology.
    """
    #: Models LED as 32bit (8 bits used) string, where the LSB switches the right LED.
    leds: int = field(default=0)

    #: Front Plane signal generator with sine/square and 2 aux outputs
    signal_generator: SignalGenerator = field(default_factory=SignalGenerator)


def _register_deprecation_shim():
    """Register the old front_panel module in sys.modules for backward compat.

    This ensures ``import pybrid.lucidac.front_panel`` resolves without
    requiring an explicit import that triggers a DeprecationWarning at
    framework-internal load time.  The shim module itself is loaded once
    with the warning suppressed.
    """
    import sys
    import warnings
    shim_name = "pybrid.lucidac.front_panel"
    if shim_name not in sys.modules:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            import importlib
            importlib.import_module(shim_name)

_register_deprecation_shim()

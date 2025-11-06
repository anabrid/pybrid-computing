# Copyright (c) 2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import typing
from dataclasses import field, dataclass
from enum import Enum

from pybrid.base.proto import main_pb2 as pb
from pybrid.redac.entities import Entity, EntityType, EntityClass

class WaveForm(int, Enum):
    """
    Output mode for the LUCIDAC's signal generator.
    """
    #: Output sine signal ONLY
    SINE = 0
    #: Output sine and rect signals at the same time
    SINE_AND_SQUARE = 1
    #: output ONLY triangle signal from the sine plug
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
class FrontPanel(Entity):
    """
    Class modelling a LUCIDAC front panel with (configurable) LEDs and Signal Generator.
    """
    #: Models LED as 32bit (8 bits used) string, where the LSB switches the right LED.
    leds: int = field(default=0)

    #: Front Panel signal generator with sine/square and 2 aux outputs
    signal_generator: SignalGenerator = field(default_factory=SignalGenerator)

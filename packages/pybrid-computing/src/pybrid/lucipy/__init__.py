"""
Lucipy: High-level Python interface for LUCIDAC analog computers.

This is the canonical package location.
"""

import numpy as np

from pybrid.lucipy.elements import (
    Integrator,
    Multiplier,
    Identity,
    Constant,
    Input,
    Output,
    Element,
    
)
from pybrid.lucipy.circuits import Circuit
from pybrid.lucidac.front_plane import WaveForm
from pybrid.lucipy.computer import LucipyWrapper as LUCIDAC


def time_series(sample_rate, sample_count):
    """
    Compute a time series array for sampled data.

    :param sample_rate: Samples per second.
    :param sample_count: Total number of samples.
    :returns: Numpy array of time values in seconds.
    """
    sample_period_micros = 1_000_000 // sample_rate
    sample_period = sample_period_micros / 1_000_000
    real_sample_time = sample_period * (sample_count - 1)
    return np.linspace(0, real_sample_time, sample_count)


__all__ = [
    'Circuit',
    'Integrator',
    'Multiplier',
    'Identity',
    'Constant',
    'Input',
    'Output',
    'Element',
    'LUCIDAC',
    'time_series',
    'WaveForm'
]

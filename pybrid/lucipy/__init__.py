from pybrid.lucipy.circuits import *
from pybrid.lucipy.computer import LUCIDACWrapper as LUCIDAC

import numpy as np

def time_series(sample_rate, sample_count):
    sample_period_micros = 1_000_000 // sample_rate
    sample_period = sample_period_micros / 1_000_000
    real_sample_time = sample_period * (sample_count - 1)
    return np.linspace(0, real_sample_time, sample_count)
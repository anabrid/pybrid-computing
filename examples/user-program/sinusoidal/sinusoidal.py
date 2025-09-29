# Example of a UserProgram configuring a harmonic oscillator on the REDAC. Use as
#   pybrid redac -h <host> user-program path/to/this/file.py

import matplotlib.pyplot as plt
import numpy as np
from pybrid.base.hybrid.programs import SingleRun
from pybrid.redac import REDAC, Run, RunConfig, DAQConfig


class UserProgram(SingleRun):
    # Shortcut to configure run
    RUN_CONFIG = RunConfig(op_time=8_000_560_000)
    DAQ_CONFIG = DAQConfig(num_channels=2, sample_rate=400_000)

    def set_configuration(self, run: Run, computer: REDAC):
        # Reference to first cluster on first carrier board
        cluster = computer.carriers[0].clusters[0]
        omega = 2.* 3.141 * 0.5
        # Configure harmonic oscillator
        cluster.route(0, 0, -1.0 * omega, 1)
        cluster.route(1, 1, 1.0 * omega, 0)
        # Configure initial value
        cluster.m0block.elements[0].ic = -0.42

        # Configure which signals you want to capture
        computer.daq.capture(cluster.m0block.elements[0], cluster.m0block.elements[1])

    def run_done(self, run: Run):
        # This function is called once the run is done
        if run.data:
            for label, channel in run.data.items():
                x = time_series(self.DAQ_CONFIG.sample_rate, len(channel))
                plt.plot(x, channel, label=label)
            plt.legend(bbox_to_anchor=(0, 1.02, 1, 0.2), loc="lower left", mode="expand", ncol=2)
            plt.ylabel("Amplitude x")
            plt.xlabel("'Time' t")
            plt.show()
        self.print("Done.")

def time_series(sample_rate, sample_count):
    sample_period_micros = 1_000_000 // sample_rate
    sample_period = sample_period_micros / 1_000
    real_sample_time = sample_period * (sample_count - 1)
    return np.linspace(0, real_sample_time, sample_count)
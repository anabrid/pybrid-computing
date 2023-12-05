# Example of a UserProgram configuring a harmonic oscillator on the REDAC. Use as
#   anabrid redac -h <host> user-program path/to/this/file.py

import matplotlib.pyplot as plt

from pyanabrid.base.hybrid.programs import SimpleRun
from pyanabrid.redac import REDAC, Run, RunConfig, DAQConfig


class UserProgram(SimpleRun):
    # Shortcut to configure run
    RUN_CONFIG = RunConfig(op_time=2_560_000)
    DAQ_CONFIG = DAQConfig(num_channels=2, sample_rate=100_000)

    def set_configuration(self, run: Run, computer: REDAC):
        # Reference to first cluster on first carrier board
        cluster = computer.carriers[0].clusters[0]

        # Configure harmonic oscillator
        cluster.route(8, 0, -1.0, 9)
        cluster.route(9, 1, 1.0, 8)
        # Configure initial value
        cluster.m0block.elements[0].ic = 0.42

    def run_done(self, run: Run):
        # This function is called once the run is done
        if run.data:
            t = [t_/10 for t_ in run.data.pop("t")]
            for channel in run.data.values():
                plt.plot(t, channel)
            plt.ylabel("Amplitude x")
            plt.xlabel("'Time' t")
            plt.show()
        self.print("Done.")

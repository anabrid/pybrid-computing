# Example of a UserProgram configuring a harmonic oscillator on the REDAC. Use as
#   pybrid redac -h <host> user-program path/to/this/file.py

import matplotlib.pyplot as plt

from pybrid.base.hybrid.programs import SingleRun
from pybrid.redac import REDAC, Run, RunConfig, DAQConfig


class UserProgram(SingleRun):
    # Shortcut to configure run
    RUN_CONFIG = RunConfig(op_time=2_560_000)
    DAQ_CONFIG = DAQConfig(sample_rate=20_000)

    def set_configuration(self, run: Run, computer: REDAC):
        for carrier in computer.carriers:
            for cluster in carrier.clusters:
                # Configure harmonic oscillator
                cluster.route(0, 0, -1.0, 1)
                cluster.route(1, 1, 1.0, 0)
                # Configure initial value
                cluster.m0block.elements[0].ic = 0.42

                # Configure which signals you want to capture
                computer.daq.capture(cluster.m0block.elements[0], cluster.m0block.elements[1])

    def run_done(self, run: Run):
        # This function is called once the run is done
        if run.data:
            for label, channel in run.data.items():
                plt.plot(channel, label=label)
            plt.legend(bbox_to_anchor=(0, 1.02, 1, 0.2), loc="lower left", mode="expand", ncol=2)
            plt.ylabel("Amplitude x")
            plt.xlabel("'Time' t")
            plt.show()
        self.print("Done.")

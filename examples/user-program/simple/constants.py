# Example of a UserProgram configuring a harmonic oscillator on the REDAC. Use as
#   pybrid redac -h <host> user-program path/to/this/file.py

import matplotlib.pyplot as plt

from pybrid.base.hybrid.programs import SingleRun
from pybrid.redac import REDAC, DAQConfig, Path, Run, RunConfig
from pybrid.redac.entities import Loc


class UserProgram(SingleRun):
    # Shortcut to configure run
    RUN_CONFIG = RunConfig(op_time=1_000_000)
    DAQ_CONFIG = DAQConfig(sample_rate=50_000)

    def set_configuration(self, run: Run, computer: REDAC):
        for carrier in computer.carriers:
            for idx, cluster in enumerate(carrier.clusters, start=1):
                cluster.add_constant(7, 0.1 * idx, 0)
                computer.daq.capture(cluster.m0block.elements[0])

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

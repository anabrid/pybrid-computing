# Example of a UserProgram configuring a harmonic oscillator on the REDAC. Use as
#   pybrid redac -h <host> user-program path/to/this/file.py

import matplotlib.pyplot as plt

from pybrid.base.hybrid.programs import SingleRun
from pybrid.redac import REDAC, DAQConfig, Path, Run, RunConfig
from pybrid.redac.carrier import Carrier


class UserProgram(SingleRun):
    # Shortcut to configure run
    RUN_CONFIG = RunConfig(op_time=1_000_000)
    DAQ_CONFIG = DAQConfig(num_channels=4, sample_rate=100_000)

    def set_configuration(self, run: Run, computer: REDAC):

        # And then we try to configure one sinusoidal between mREDACs.
        # Assumptions: mREDAC slots 0 & 2 used
        # TODO: Implement backplane identification and check assumptions

        carrier_0: Carrier = computer.get_entity(Path.parse("00-00-00-00-00-00"))
        carrier_2: Carrier = computer.get_entity(Path.parse("00-00-00-00-00-02"))
        # carrier_2: Carrier =  computer.get_entity(Path.parse("04-E9-E5-18-14-84"))
        # We use the first cluster on both carriers
        cluster_0, cluster_2 = carrier_0.clusters[0], carrier_2.clusters[0]

        # First integrator from mREDAC_0 cluster_0
        cluster_0.m0block.elements[4].ic = -0.82
        cluster_0.ublock.connect(4, 16)
        cluster_0.cblock.elements[16].factor = -1.0
        # Signal number 16 is 8. lane of T-block, thus muxes 32..35 are involved
        computer.router.route(cluster_0.loc() / 16, cluster_2.loc() / 16)

        cluster_2.iblock.connect(16, 4)
        # Second integrator
        cluster_2.m0block.elements[4].ic = 0.3
        cluster_2.ublock.connect(4, 16)
        cluster_2.cblock.elements[16].factor = 1.0
        # Signal number 16 is 8th lane of T-Block, thus muxes 32..35 are involved
        computer.router.route(carrier_2.loc() / 0 / 16, carrier_0.loc() / 0 / 16)

        cluster_0.iblock.connect(16, 4)
        computer.daq.capture(cluster_0.m0block.elements[4], cluster_2.m0block.elements[4])

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

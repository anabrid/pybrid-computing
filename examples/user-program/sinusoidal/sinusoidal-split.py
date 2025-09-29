# Example of a UserProgram configuring a harmonic oscillator on the REDAC. Use as
#   pybrid redac -h <host> user-program path/to/this/file.py

import matplotlib.pyplot as plt

from pybrid.base.hybrid.programs import SingleRun
from pybrid.redac import REDAC, Run, RunConfig, DAQConfig, Path


class UserProgram(SingleRun):
    # Shortcut to configure run
    RUN_CONFIG = RunConfig(op_time=1_000_000)
    DAQ_CONFIG = DAQConfig(num_channels=4, sample_rate=100_000)

    def set_configuration(self, run: Run, computer: REDAC):
        # For each carrier, we configure one sinusoidal between clusters on the same carrier
        for idx, carrier in enumerate(computer.carriers):
            # Disconnect T-block as far as possible
            carrier.tblock.muxes = [0] * 96

            # Route sinusoidal between two clusters on the same carrier
            cluster_a, cluster_b = carrier.clusters[0:2]
            # First integrator to second integrator
            cluster_a.m0block.elements[0].ic = -0.05 * (idx + 1)
            cluster_a.ublock.connect(0, 8)
            cluster_a.cblock.elements[8].factor = -1.0
            carrier.tblock.muxes[2] = 1
            cluster_b.iblock.connect(8, 0)
            # Second integrator back to first
            cluster_b.ublock.connect(0, 9)
            cluster_b.cblock.elements[9].factor = 1.0
            carrier.tblock.muxes[5] = 2
            cluster_a.iblock.connect(9, 0)

            # Capture data
            computer.daq.capture(cluster_a.m0block.elements[0], cluster_b.m0block.elements[0])

        # And then we try to configure one sinusoidal between mREDACs.
        # Assumptions: mREDAC slots 0 & 2 used
        # TODO: Implement backplane identification and check assumptions
        carrier_0, carrier_2 = (
            computer.get_entity(Path.parse("00-00-00-00-00-00")),
            computer.get_entity(Path.parse("00-00-00-00-00-02")),
        )
        # We use the first cluster on both carriers
        cluster_0, cluster_2 = carrier_0.clusters[0], carrier_2.clusters[0]

        # Set st0block to something "useless"
        carrier_0.st0block.muxes = [0] * 96

        # First integrator from mREDAC_0 cluster_0
        cluster_0.m0block.elements[4].ic = -0.82
        cluster_0.ublock.connect(4, 16)
        cluster_0.cblock.elements[16].factor = -1.0
        # Signal number 16 is 8. lane of T-block, thus muxes 32..35 are involved
        carrier_0.tblock.muxes[32 + 1] = 0
        # / Configure ST0 such that carrier_2 receives signal from carrier_0
        carrier_0.st0block.muxes[32 + 1] = 3
        # \
        carrier_2.tblock.muxes[32 + 0] = 1
        cluster_2.iblock.connect(16, 4)
        # Second integrator
        cluster_2.m0block.elements[4].ic = 0.3
        cluster_2.ublock.connect(4, 16)
        cluster_2.cblock.elements[16].factor = 1.0
        # Signal number 16 is 8th lane of T-Block, thus muxes 32..35 are involved
        carrier_2.tblock.muxes[32 + 1] = 0
        # / Configure ST0 such that carrier_0 receives signal from carrier_2
        carrier_0.st0block.muxes[32 + 3] = 1
        # \
        carrier_0.tblock.muxes[32 + 0] = 1
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

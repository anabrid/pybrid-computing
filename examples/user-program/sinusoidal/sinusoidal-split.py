# Example of a UserProgram configuring a harmonic oscillator on the REDAC. Use as
#   pybrid redac -h <host> user-program path/to/this/file.py

import matplotlib.pyplot as plt
from pybrid.base.hybrid.programs import SimpleRun

from pybrid.redac import REDAC, Run, RunConfig, DAQConfig


class UserProgram(SimpleRun):
    # Shortcut to configure run
    RUN_CONFIG = RunConfig(op_time=1_000_000)
    DAQ_CONFIG = DAQConfig(num_channels=4, sample_rate=100_000)

    def set_configuration(self, run: Run, computer: REDAC):
        # For each carrier, we configure one sinusoidal between clusters on the same carrier
        for carrier in computer.carriers:
            # Disconnect T-block as far as possible
            carrier.tblock.muxes = [0] * 96

            # Route sinusoidal between two clusters on the same carrier
            cluster_a, cluster_b = carrier.clusters[0:2]
            # First integrator to second integrator
            cluster_a.m0block.elements[0].ic = -0.2
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
        # First, with the fixed connections
        # Assumptions: mREDAC slots 0 & 2 used
        # TODO: Implement backplane identification and check assumptions
        carrier_0, carrier_2 = computer.carriers[0:2]
        if carrier_0.id_ != "04-E9-E5-18-14-61":
            carrier_0, carrier_2 = carrier_2, carrier_0
        # We use the first cluster on both carriers
        cluster_0, cluster_2 = carrier_0.clusters[0], carrier_2.clusters[0]

        # Fixed connections look like this
        # carrier_0.BPL_BL_OUT[12..15] -> carrier_2.BPL_BL_IN[8..11]
        # carrier_2.BPL_BL_OUT[8..11] -> carrier_0.BPL_BL_IN[12..15]

        # First integratorg

        cluster_0.m0block.elements[4].ic = -0.82
        cluster_0.ublock.connect(4, 14)
        cluster_0.cblock.elements[14].factor = -1.0
        # Signal number 14 is 6. lane of T-block, thus muxes 24..27 are involved
        carrier_0.tblock.muxes[24 + 0] = 1
        # And it's "reduced by 4" in fixed connections on backplane
        # -> 2. lane of T-block on carrier_2 involves muxes 8..11
        carrier_2.tblock.muxes[8 + 1] = 0
        cluster_2.iblock.connect(10, 4)
        # Second integrator
        cluster_2.m0block.elements[4].ic = 0.0
        cluster_2.ublock.connect(4, 11)
        cluster_2.cblock.elements[11].factor = 1.0
        # Signal number 11 is 4th lane of T-Block, thus muxes 12..15 are involved
        carrier_2.tblock.muxes[12 + 0] = 1
        # And it's "increased by 4" in fixed connections on backplane
        # -> 8th lane of T-block on carrier_0 involves muxes 28..31
        carrier_0.tblock.muxes[28 + 1] = 0
        cluster_0.iblock.connect(15, 4)

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

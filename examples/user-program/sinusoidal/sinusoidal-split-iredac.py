# Example of a UserProgram configuring a harmonic oscillator on the REDAC. Use as
#   pybrid redac -h <host> user-program path/to/this/file.py

import matplotlib.pyplot as plt

from pybrid.base.hybrid.programs import SimpleRun
from pybrid.redac import REDAC, Run, RunConfig, DAQConfig, Path


class UserProgram(SimpleRun):
    # Shortcut to configure run
    RUN_CONFIG = RunConfig(op_time=1_000_000)
    DAQ_CONFIG = DAQConfig(sample_rate=50_000)

    def set_configuration(self, run: Run, computer: REDAC):
        # For each carrier, we configure one sinusoidal between clusters on the same carrier
        for idx, carrier in enumerate(computer.carriers):
            # Route sinusoidal between two clusters on the same carrier
            cluster_a, cluster_b = carrier.clusters[0:2]
            # First integrator to second integrator
            cluster_a.m0block.elements[0].ic = -0.2 - idx * 0.01
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

        # And then we try to configure one sinusoidal between iREDACs.
        # Assumptions: mREDAC slots 0 used
        # TODO: Implement backplane identification and check assumptions
        i0_m0, i1_m0 = (
            computer.get_entity(Path.parse("00-00-00-00-00-00")),
            computer.get_entity(Path.parse("01-00-00-00-00-00")),
        )
        # We use the first cluster on both carriers
        i0_m0_cl0, i1_m0_cl0 = i0_m0.clusters[0], i1_m0.clusters[0]

        # First integrator from iREDAC0 to iREDAC1
        # Basically the same code for signal 24 did not work. But maybe just a stupid error
        i0_m0_cl0.m0block.elements[4].ic = -0.82
        i0_m0_cl0.ublock.connect(4, 31)
        i0_m0_cl0.cblock.elements[31].factor = -1.0
        i0_m0.tblock.muxes[92] = 1
        i0_m0.st0block.muxes[92] = 1
        i1_m0.st0block.muxes[93] = 0
        i1_m0.tblock.muxes[93] = 0
        i1_m0_cl0.iblock.connect(31, 4)

        # Second integrator from iREDAC1 to iREDAC0
        i1_m0_cl0.m0block.elements[4].ic = 0
        i1_m0_cl0.ublock.connect(4, 16)
        i1_m0_cl0.cblock.elements[16].factor = 1.0
        # Signal number 16 is 8th lane of T-Block, thus muxes 32..35 are involved
        i1_m0.tblock.muxes[32 + 0] = 1
        # / Configure T-blocks on backplane
        # carrier_2.ST0 such that signal from mREDAC0 is sent to TAUX
        i1_m0.st0block.muxes[32 + 0] = 1
        # carrier_0.ST0 such that signal from TAUX is sent to mREDAC0
        i0_m0.st0block.muxes[32 + 1] = 0
        # \
        i0_m0.tblock.muxes[32 + 1] = 0
        i0_m0_cl0.iblock.connect(16, 4)

        computer.daq.capture(i0_m0_cl0.m0block.elements[4], i1_m0_cl0.m0block.elements[4])

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

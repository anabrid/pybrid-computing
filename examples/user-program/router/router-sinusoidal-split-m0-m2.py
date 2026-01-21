# Example of a UserProgram configuring a harmonic oscillator on the REDAC. Use as
#   pybrid redac -h <host> user-program path/to/this/file.py

from ipaddress import IPv4Address

import matplotlib.pyplot as plt

from pybrid.base.hybrid.programs import SingleRun
from pybrid.redac import REDAC, Run, RunConfig, DAQConfig, Path


class UserProgram(SingleRun):
    # Shortcut to configure run
    RUN_CONFIG = RunConfig(op_time=1_000_000, ic_time=500_000)
    DAQ_CONFIG = DAQConfig(sample_rate=20_000)

    def set_configuration(self, run: Run, computer: REDAC):
        router = computer.router
        # Assumptions: mREDAC slots 0,2 used
        # TODO: Implement backplane identification and check assumptions
        i0_m0, i0_m2 = (
            computer.get_entity(Path.parse("00-00-00-00-00-00")),
            computer.get_entity(Path.parse("00-00-00-00-00-02")),
        )

        # For each carrier, we configure one sinusoidal between clusters on the same carrier
        for idx, carrier in enumerate(computer.carriers):
            # Route sinusoidal between two clusters on the same carrier
            cluster_a, cluster_b = carrier.clusters[0:2]

            # First integrator to second integrator
            cluster_a.m0block.elements[2].ic = -0.2 - idx * 0.01
            cluster_a.ublock.connect(2, 8)
            cluster_a.cblock.elements[8].factor = -1.0
            router.route(carrier.tblock.loc() / 0 / 8, carrier.tblock.loc() / 1 / 8)
            cluster_b.iblock.connect(8, 2)

            # Second integrator back to first
            cluster_b.ublock.connect(2, 9)
            cluster_b.cblock.elements[9].factor = 1.0
            router.route(carrier.tblock.loc() / 1 / 9, carrier.tblock.loc() / 0 / 9)
            cluster_a.iblock.connect(9, 2)

            # Capture data
            computer.daq.capture(cluster_a.m0block.elements[2], cluster_b.m0block.elements[2])

        # Sinusoidal between m0.cl0 <-> m2.cl0
        i0_m0_cl0, i0_m2_cl0 = i0_m0.clusters[0], i0_m2.clusters[0]
        # ->
        i0_m0_cl0.m0block.elements[4].ic = -0.82
        i0_m0_cl0.ublock.connect(4, 31)
        i0_m0_cl0.cblock.elements[31].factor = -1.0
        router.route(i0_m0.tblock.loc() / 0 / 31, i0_m2.tblock.loc() / 0 / 31)
        i0_m2_cl0.iblock.connect(31, 4)
        # <-
        i0_m2_cl0.m0block.elements[4].ic = 0
        i0_m2_cl0.ublock.connect(4, 16)
        i0_m2_cl0.cblock.elements[16].factor = 1.0
        router.route(i0_m2.tblock.loc() / 0 / 16, i0_m0.tblock.loc() / 0 / 16)
        i0_m0_cl0.iblock.connect(16, 4)
        # DAQ
        computer.daq.capture(i0_m0_cl0.m0block.elements[4], i0_m2_cl0.m0block.elements[4])

        # Sinusoidal with upscaling between m0.cl1 <-> m2.cl1
        # NOTE: Gives sinusoidal, but not quite the expected frequency.
        i0_m0_cl1, i0_m2_cl1 = i0_m0.clusters[1], i0_m2.clusters[1]
        # ->
        i0_m0_cl1.m0block.elements[4].ic = -0.5
        i0_m0_cl1.ublock.connect(4, 30)
        i0_m0_cl1.cblock.elements[30].factor = -1/8
        # Source mREDAC needs to know whether to set 0.1 or 1 as calibration input
        # TODO: Move all of this (maybe including factors) into router.route
        router.route(i0_m0.tblock.loc() / 1 / 30, i0_m2.tblock.loc() / 1 / 30)
        i0_m2_cl1.iblock.connect(30, 4)
        i0_m2_cl1.iblock.upscaling[30] = True
        # Target mREDAC needs to know where to send calibration data
        # TODO: Move all of this (maybe including factors) into router.route
        # <-
        i0_m2_cl1.m0block.elements[4].ic = 0
        i0_m2_cl1.ublock.connect(4, 17)
        i0_m2_cl1.cblock.elements[17].factor = 1/8
        router.route(i0_m2.tblock.loc() / 1 / 17, i0_m0.tblock.loc() / 1 / 17)
        i0_m0_cl1.iblock.connect(17, 4)
        i0_m0_cl1.iblock.upscaling[17] = True
        # DAQ
        computer.daq.capture(i0_m0_cl1.m0block.elements[4], i0_m2_cl1.m0block.elements[4])


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

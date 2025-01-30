# Example of a UserProgram configuring a harmonic oscillator on the REDAC. Use as
#   pybrid redac -h <host> user-program path/to/this/file.py
import typing
from itertools import cycle
import matplotlib.pyplot as plt

from pybrid.base.hybrid import BaseRun, AnalogComputer
from pybrid.base.hybrid.programs import RunEvaluateReconfigureLoop
from pybrid.redac import REDAC, Run, RunConfig, DAQConfig

decay_rate = iter(cycle(map(lambda x: x / 100.0, reversed(range(0, 100, 5)))))
figure, axes = plt.subplots()
axes.set_xlabel("'Time' t")
axes.set_ylabel("Amplitude x")


class UserProgram(RunEvaluateReconfigureLoop):
    # Shortcut to configure run
    RUN_CONFIG = RunConfig(op_time=2_560_000)
    DAQ_CONFIG = DAQConfig(num_channels=8, sample_rate=50_000)

    def initial_configuration(self, run: Run, computer: REDAC):
        for carrier in computer.carriers:
            for cluster in carrier.clusters:
                # Configure harmonic oscillator
                cluster.route(0, 0, next(decay_rate), 0)
                cluster.route(1, 1, next(decay_rate), 1)
                # Configure initial value
                cluster.m0block.elements[0].ic = -0.42
                cluster.m0block.elements[1].ic = -0.42

                # Configure which signals you want to capture
                computer.daq.capture(cluster.m0block.elements[0], cluster.m0block.elements[1])

    def next_configuration(self, run: BaseRun, computer: AnalogComputer, previous_runs: typing.List[BaseRun]):
        # Configuration from initial_configuration is kept
        # You could change the configuration partially here if you wanted
        pass

    def run_done(self, run: Run):
        # This function is called once the run is done
        self.print(f"Run #{len(self.runs)} done.")
        if run.data:
            for label, channel in run.data.items():
                axes.plot(channel, label=label)

        # Return True to keep going
        return not len(self.runs) >= 10

    def loop_done(self, runs: typing.List[Run]):
        axes.legend(bbox_to_anchor=(0, 1.02, 1, 0.2), loc="lower left", mode="expand", ncol=2)
        plt.show()

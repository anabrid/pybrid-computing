import typing
import warnings
from datetime import datetime

import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

from pybrid.base.hybrid.programs import RunEvaluateReconfigureLoop
from pybrid.redac import REDAC, DAQConfig, Run, RunConfig

# Define accuracy target
t_min, t_max = 18, 20
y_min, y_max = 0.14, 0.18

figure, axes = plt.subplots()
axes.set_xlabel("'Time' t")
axes.set_ylabel("Amplitude y")
accuracy_area = Rectangle(
    (t_min, y_min),
    t_max - t_min,
    y_max - y_min,
    color="green",
    fill=False,
)
axes.add_patch(accuracy_area)


class UserProgram(RunEvaluateReconfigureLoop):
    # Shortcut to configure run
    RUN_CONFIG = RunConfig(op_time=1_000_000)
    DAQ_CONFIG = DAQConfig(sample_rate=20_000)

    def initial_configuration(self, run: Run, computer: REDAC):
        for carrier in computer.carriers:
            for cluster in carrier.clusters:
                # Configure harmonic oscillator
                decay_rate = 0.1
                cluster.route(0, 0, decay_rate, 0)
                cluster.route(1, 1, decay_rate, 1)
                # Configure initial value
                cluster.m0block.elements[0].ic = -0.42
                cluster.m0block.elements[1].ic = -0.42
                # Configure which signals you want to capture
                computer.daq.capture(cluster.m0block.elements[0], cluster.m0block.elements[1])

    def next_configuration(self, *args, **kwargs):
        # Configuration from initial_configuration is kept
        pass

    def run_done(self, run: Run):
        # This function is called once the run is done
        self.print(f"{datetime.now()}: Run done.")
        if run.data:
            # Clear the axes and replot data
            for line in axes.get_lines():
                line.remove()
            for label, channel in run.data.items():
                axes.plot(channel, label=label)
            plt.pause(0.1)  # Pause to update the plot

            # Check whether endpoints are good enough
            for label, channel in run.data.items():
                t, y_end = (len(channel), channel[-1])
                if not t_min <= t <= t_max or not y_min <= y_end <= y_max:
                    global accuracy_area
                    accuracy_area.set_color("red")
                    accuracy_area.set_fill(True)
                    warnings.warn(f"End point {(t, y_end)} of {label} is too inaccurate.")
        else:
            raise RuntimeError("No data received.")

        # This RECL should run forever (or fail due to inaccuracies)
        # Try to prevent unnecessary memory usage
        del self.runs[:-1]
        return True

    def loop_done(self, runs: typing.List[Run]):
        plt.close(figure)

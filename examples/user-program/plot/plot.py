# Example of a UserProgram configuring a harmonic oscillator on the REDAC. Use as
#   pybrid redac -h <host> user-program path/to/this/file.py
import json
import os
import typing

import matplotlib.pyplot as plt
import numpy as np
from docutils import examples

from pybrid.base.hybrid import RunEvaluateReconfigureLoop
from pybrid.base.hybrid.programs import SingleRun
from pybrid.redac import REDAC, DAQConfig, Path, Run, RunConfig
from pybrid.redac.carrier import ADCChannel, Carrier

ROOT_DIR = "examples/user-program/plot"
EXAMPLES = [
    ("mass_spring", 10_000_000, 2, 50_000, False),
    ##('dadras', 20_000_000, 2, 25_000, True),
    # ('lorenz', 40_000_000, 2, 100_000, True),
    # ('hindmarsh-rose', 100_000_000, 2, 25_000, False),
    # ('roessler', 10_000_000, 2, 50_000, True),
    # ('harmonic', 10_000_000, 2, 50_000, False),
    # ('nose_hoover', 10_000_000, 2, 50_000, True),
    # ('zombie', 10_000_000, 2, 50_000, False),
    # ('sprott_caotic', 10_000_000, 2, 50_000, True),
    # ('halvorsen', 10_000_000, 2, 50_000, True),
    # ('gauss', 1_400_000, 2, 50_000, False),
    # ('jerk', 20_000_000, 2, 25_000, True),
    ##('sprott', 50_000_000, 2, 25_000, True),
    ##('henon_heils', 10_000_000, 2, 50_000, True),
    ##('euler', 10_000_000, 2, 50_000, True),
    # ('decay', 10_000_000, 2, 50_000, False),
    # ('four_wing', 30_000_000, 2, 25_000, True),
    # ('mathieu', 10_000_000, 2, 50_000, False),
    # ('duffing', 10_000_000, 2, 50_000, True),
]


class UserProgram(RunEvaluateReconfigureLoop):
    # Shortcut to configure run

    RUN_CONFIG = RunConfig(op_time=10_000_000)
    DAQ_CONFIG = DAQConfig(num_channels=2, sample_rate=50_000)

    example_idx = 0
    carrier_config = None

    def initial_configuration(self, run: Run, computer: REDAC):
        self.next_configuration(run, computer, list())

    def next_configuration(self, run: Run, computer: REDAC, previous_runs):
        name, op_time, num_channels, sample_rate, xy_plot = EXAMPLES[self.example_idx]

        run.config.op_time = op_time
        run.daq.num_channels = num_channels
        run.daq.sample_rate = sample_rate

        print("Example:", name)
        with open(os.path.join(ROOT_DIR, "config", name + ".json"), "r") as f:
            config = json.loads(f.read())

        for carrier_key, carrier_config in config.items():
            self.carrier_config = Path() / carrier_key
            carrier: Carrier = computer.get_entity(Path.parse(carrier_key))

            t_config = carrier_config["/T"]

            t_muxes = t_config["muxes"]
            for idx, value in enumerate(t_muxes):
                if value is not None:
                    carrier.tblock.muxes[idx] = value

            carrier.adc_channels = list(map(lambda idx: ADCChannel(index=idx), carrier_config["adc_channels"]))

            for idx in range(3):
                cluster_key = f"/{idx}"
                if cluster_key not in carrier_config:
                    continue
                cluster = carrier.clusters[idx]

                cluster_config = carrier_config[cluster_key]
                c_config = cluster_config["/C"]
                c_elems = c_config["elements"]
                for idx, value in enumerate(c_elems):
                    cluster.cblock.elements[idx].factor = value

                u_config = cluster_config["/U"]
                cluster.set_constant(u_config.get("constant", False))

                u_outputs = u_config["outputs"]
                for idx, value in enumerate(u_outputs):
                    cluster.ublock.outputs[idx] = value

                i_config = cluster_config["/I"]
                i_upscaling = i_config["upscaling"]
                for idx, value in enumerate(i_upscaling):
                    cluster.iblock.upscaling[idx] = value

                i_outputs = i_config["outputs"]
                for idx, value in enumerate(i_outputs):
                    cluster.iblock.outputs[idx] = set(value)

                m0_config = cluster_config["/M0"]
                m0_elems = m0_config["elements"]
                for idx, elem in enumerate(m0_elems):
                    itor = cluster.m0block.elements[idx]
                    itor.ic = elem["ic"]
                    itor.k = elem["k"]

    def run_done(self, run: Run):
        # This function is called once the run is done
        if not run.data:
            return

        name, op_time, num_channels, sample_rate, xy_plot = EXAMPLES[self.example_idx]

        series = []
        labels = []
        for label, channel in run.data.items():
            if label.to_root() != self.carrier_config:
                continue
            # plt.plot(time, channel, label=label)
            series.append(channel)
            labels.append(label)

        if xy_plot:
            assert len(series) >= 2
            plt.plot(series[0], series[1])
            plt.xlabel("X")
            plt.ylabel("Y")
            plt.xlim(-1, 1)
            plt.ylim(-1, 1)
        else:
            for idx, serie in enumerate(series):
                time = np.arange(len(serie)) / self.DAQ_CONFIG.sample_rate
                plt.plot(time, serie, label=labels[idx])
            plt.xlabel("'Time' t")
            plt.ylabel("Amplitude x")
        plt.title(name)
        plt.draw()
        plt.savefig(os.path.join(ROOT_DIR, "plots", "hw", name + ".jpg"))
        plt.show()
        self.print("Done.")

        self.example_idx += 1
        return self.example_idx < len(EXAMPLES)

    def loop_done(self, runs: typing.List[Run]):
        return

import asyncio
import io
import logging
from ipaddress import IPv4Address, ip_network

import numpy as np
from matplotlib import pyplot as plt
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from pybrid.base.utils.logging import set_pybrid_logging_level
from pybrid.lucidac.controller import Controller as LUCIDACController
from pybrid.redac import Controller as REDACController
from pybrid.redac import DAQConfig, Path, RunConfig
from pybrid.redac.carrier import ADCChannel, Carrier

set_pybrid_logging_level(logging.ERROR)


class Reporter:
    canvas: canvas.Canvas
    currentHeight: int = 0
    pageWidth: int = 0
    pageHeight: int = 0
    fontSize: int = 0
    padding: int = 20
    spacing: int = 10

    def __init__(self, output="report.pdf", pagesize=A4) -> None:
        self.canvas = canvas.Canvas(output, pagesize=pagesize)
        self.pageWidth, self.pageHeight = pagesize
        self.init_page()

    def init_page(self):
        self.currentHeight = self.pageHeight - self.padding

    def ensure_height(self, height):
        if height > self.currentHeight:
            self.nextPage()

    def drawString(self, text, fontSize, **kwargs):
        self.ensure_height(fontSize)
        self.currentHeight -= fontSize
        self.canvas.setFont("Helvetica", fontSize)
        self.canvas.drawString(x=self.padding, y=self.currentHeight, text=text, **kwargs)
        self.currentHeight -= self.spacing

    def maxWidth(self):
        return self.pageWidth - 2 * self.padding

    def drawPlot(self, fig: plt.Figure, width: int = 0, height: int = 400) -> None:
        if width == 0:
            width = self.maxWidth()
        self.ensure_height(height)
        buf = io.BytesIO()
        fig.set_size_inches(width / 100, height / 100)
        fig.savefig(buf, format="png", dpi=300)
        buf.seek(0)
        self.currentHeight -= height
        center = (self.pageWidth - width) / 2
        self.canvas.drawImage(ImageReader(buf), center, self.currentHeight, width=width, height=height)
        self.currentHeight -= self.spacing

    def nextPage(self):
        self.canvas.showPage()
        self.init_page()

    def save(self, filename="reporter.pdf"):
        self.canvas.save()

    def box_plot(self, labels, distributions, title="") -> None:
        fig, ax = plt.subplots()
        ax.boxplot(distributions, tick_labels=labels, showfliers=False)
        ax.set_ylabel("Value")
        ax.set_title(title)
        ax.tick_params(axis="x", rotation=90)
        fig.tight_layout(pad=3)
        self.drawPlot(fig)
        plt.close(fig)

    def line_plot(self, labels, values, title="") -> None:
        fig, ax = plt.subplots()
        for distribution in values:
            ax.plot(distribution)
        ax.set_ylabel("Value")
        ax.set_title(title)
        ax.tick_params(axis="x", rotation=90)
        fig.tight_layout(pad=3)
        self.drawPlot(fig)
        plt.close(fig)


async def sin_test(controller: REDACController | LUCIDACController, reporter: Reporter) -> None:
    print("Harmonic oscillator test")

    reporter.drawString("Harmonic oscillator test", 18)
    reporter.drawString("Run sinus for some periods and compare against true value.", 12)

    computer = controller.computer

    for periods in (1, 10, 20):
        reporter.drawString("periods = " + str(periods), 12)
        for carrier in computer.carriers:
            for cluster_idx, cluster in enumerate(carrier.clusters):
                computer.reset()
                for sincos_idx in range(4):
                    lane_cos = sincos_idx * 2
                    lane_sin = lane_cos + 1

                    # Configure harmonic oscillator
                    cluster.route(lane_cos, lane_cos, -1.0, lane_sin)
                    cluster.route(lane_sin, lane_sin, 1.0, lane_cos)
                    # Configure initial value
                    cluster.m0block.elements[lane_cos].ic = 1.0
                    computer.daq.capture(cluster.m0block.elements[lane_cos], cluster.m0block.elements[lane_sin])

                run_config = RunConfig(op_time=(periods * 6_283_185_307) // 10_000)
                daq_config = DAQConfig(num_channels=8, sample_rate=(314_159) // 10)

                runs = await (
                    controller.create_session()
                    .set_config(computer)
                    .calibrate(gain=True, offset=True)
                    .run(config=run_config, daq=daq_config)
                    .execute()
                )
                run = runs[0]

                labels = []
                data = []
                for channel_idx, channel in enumerate(run.data):
                    if channel is None:
                        continue
                    channel = np.array(channel)
                    itor_idx = channel_idx
                    pi_values = np.linspace(0, periods * 2 * np.pi, len(channel))
                    ref = np.cos(pi_values) if channel_idx % 2 == 0 else np.sin(pi_values)
                    values = -channel - ref
                    labels.append(str(itor_idx))
                    data.append(values)
                reporter.box_plot(labels, data, title=str(cluster.path.root) + " cluster " + str(cluster_idx))


async def lane_test(controller: REDACController | LUCIDACController, reporter: Reporter) -> None:
    print("Lane Test")

    reporter.drawString("Lane test", 18)
    reporter.drawString(
        "Evaluation of each lane using constant input and probe through coef element with 0.56 and ident element.", 12
    )

    computer = controller.computer

    run_config = RunConfig(op_time=1_000_000)
    daq_config = DAQConfig(num_channels=2, sample_rate=100_000)

    for carrier in computer.carriers:
        for cluster_idx, cluster in enumerate(carrier.clusters):
            labels = []
            data = []

            lane_coef = 0.56
            for batch_idx in range(8):
                computer.reset()
                for channel_idx in range(4):
                    lane_idx = batch_idx * 4 + channel_idx

                    cluster.add_constant(lane_idx, -lane_coef, 8 + channel_idx, 1.0)
                    carrier.adc_config.append(
                        ADCChannel(index=12 + channel_idx + 16 * cluster_idx, gain=1.0, offset=0.0, probe=channel_idx)
                    )

                runs = await (
                    controller.create_session()
                    .set_config(computer)
                    .calibrate(gain=True, offset=True)
                    .run(config=run_config, daq=daq_config)
                    .execute()
                )
                run = runs[0]

                for channel_idx, channel in enumerate(run.data):
                    if channel is None:
                        continue
                    lane_idx = batch_idx * 4 + channel_idx
                    values = np.array(channel) - lane_coef
                    labels.append(str(lane_idx))
                    data.append(values)
            reporter.box_plot(labels, data, title=str(cluster.path.root) + " cluster " + str(cluster_idx))
    reporter.nextPage()


async def mul_test(controller: REDACController | LUCIDACController, reporter: Reporter) -> None:
    print("Multiplication Test")

    reporter.drawString("Multiplication test", 18)
    reporter.drawString("Evaluate each multiplication using 0.8 * 0.7 = 0.56.", 12)

    computer = controller.computer

    run_config = RunConfig(op_time=1_000_000)
    daq_config = DAQConfig(num_channels=2, sample_rate=100_000)

    for carrier in computer.carriers:
        for cluster_idx, cluster in enumerate(carrier.clusters):
            labels = []
            data = []
            computer.reset()

            lhs_const = 0.8
            rhs_const = 0.7
            for mul_idx in range(4):
                mul_lhs = 8 + mul_idx * 2
                mul_rhs = mul_lhs + 1
                mul_out = mul_idx + 8

                cluster.add_constant(mul_lhs, -lhs_const, mul_lhs, 1.0)
                cluster.add_constant(mul_rhs, -rhs_const, mul_rhs, 1.0)

                carrier.adc_config.append(
                    ADCChannel(index=mul_out + 16 * cluster_idx, gain=1.0, offset=0.0, probe=mul_idx)
                )

            runs = await (
                controller.create_session()
                .set_config(computer)
                .calibrate(gain=True, offset=True)
                .run(config=run_config, daq=daq_config)
                .execute()
            )
            run = runs[0]

            for channel_idx, channel in enumerate(run.data):
                if channel is None:
                    continue
                mul_idx = channel_idx
                values = np.array(channel) - lhs_const * rhs_const
                labels.append(str(mul_idx))
                data.append(values)
            reporter.box_plot(labels, data, title=str(cluster.path.root) + " cluster " + str(cluster_idx))
    reporter.nextPage()


async def itor_test(controller: REDACController | LUCIDACController, reporter: Reporter) -> None:
    print("Integrator Test")
    reporter.drawString("Integrator test", 18)
    reporter.drawString("Evaluate each integration with 0.1 input over time period that must reach 1.0.", 12)
    reporter.drawString("The optimal slipe then is subtracted from the probed slope.", 12)

    computer = controller.computer

    for slope in (1.0, 0.1, 0.01):
        for k in (10_000, 100):
            reporter.drawString("k = " + str(k) + " ,slope = " + str(slope), 12)

            run_config = RunConfig(op_time=int(1_000_000_000 // k / slope))
            daq_config = DAQConfig(num_channels=2, sample_rate=40_000)

            for carrier in computer.carriers:
                labels = []
                raw = []
                target = []
                for cluster_idx, cluster in enumerate(carrier.clusters):
                    computer.reset()
                    for itor_idx in range(8):
                        itor_in = itor_idx
                        itor_out = itor_idx

                        cluster.add_constant(itor_idx, -slope, itor_in, 1.0)
                        cluster.m0block.elements[itor_idx].ic = 0.0
                        cluster.m0block.elements[itor_idx].k = k
                        carrier.adc_config.append(
                            ADCChannel(index=itor_out + 16 * cluster_idx, gain=1.0, offset=0.0, probe=itor_idx)
                        )

                    runs = await (
                        controller.create_session()
                        .set_config(computer)
                        .calibrate(gain=True, offset=True)
                        .run(config=run_config, daq=daq_config)
                        .execute()
                    )
                    run = runs[0]

                    for channel_idx, channel in enumerate(run.data):
                        if channel is None:
                            continue
                        itor_idx = channel_idx
                        channel = np.array(channel)
                        values = channel - np.linspace(0.0, 1.0, len(channel))
                        labels.append(str(cluster.path / itor_idx))
                        raw.append(channel)
                        target.append(values)

                reporter.line_plot(labels, raw, title=str(carrier.path.root))
                reporter.box_plot(labels, target, title=str(carrier.path.root))
            reporter.nextPage()


async def main():
    reporter = Reporter()

    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="192.168.104.244", help="Host IP address")
    parser.add_argument("--port", type=int, default=5732, help="Port number")
    parser.add_argument("--lucidac", action="store_true", help="Use LUCIDAC controller")
    args = parser.parse_args()

    controller = LUCIDACController() if args.lucidac else REDACController()
    await controller.add_device(args.host, args.port)

    reporter.drawString("Device Report", 24)
    async with controller:
        await sin_test(controller, reporter)
        await lane_test(controller, reporter)
        await mul_test(controller, reporter)
        await itor_test(controller, reporter)

    reporter.save()


if __name__ == "__main__":
    asyncio.run(main())

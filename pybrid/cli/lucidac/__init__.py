# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import asyncio
import json
import logging
import typing
from ipaddress import ip_network
from typing import TextIO

import asyncclick as click
from asyncclick import Choice

from pybrid.base.hybrid import EntityDoesNotExist
from pybrid.cli.base import cli
from pybrid.cli.redac import redac
# from pybrid.cli.base.commands import user_program
from pybrid.lucipy.lucidac import configure_carrier
from pybrid.redac.controller import Controller
from pybrid.redac.data import DatExporter
from pybrid.redac.detect import detect_in_network
from pybrid.redac.dummy import DummyController
from pybrid.redac.run import Run, RunState, RunError

logger = logging.getLogger(__name__)


@cli.command()
@click.pass_obj
async def detect(obj):
    """
    Detect devices in local network.
    """
    print("Detecting network devices...")
    for (host, port, name) in await detect_in_network(ip_network("0.0.0.0/0")):
        print(f"{host:15}:{port:4} {name}")

@cli.group()
@click.pass_context
@click.option(
    "--host",
    "-h",
    "hosts",
    type=str,
    required=False,
    multiple=True,
    help="Network name or address of the LUCIDAC. Or address range to use for auto-detection.",
)
@click.option(
    "--port",
    "-p",
    type=int,
    default=5732,
    required=False,
    help="Network port of the LUCIDAC.",
)
@click.option(
    "--reset/--no-reset",
    is_flag=True,
    default=True,
    show_default=True,
    help="Whether to reset the LUCIDAC after connecting.",
)
@click.option(
    "--fake",
    is_flag=True,
    default=False,
    show_default=True,
    help="Whether to fake any communication, allowing you to run without any computer present.",
)
async def lucidac(ctx: click.Context, hosts: list[str], port: int, reset: bool, fake: bool):
    """
    Entrypoint for all LUCIDAC commands.

    Use :code:`pybrid lucidac --help` to list all available sub-commands.
    """

    # Some sub-commands may change default options
    # TODO: It would be cleaner to introduce a specialization of click.Group
    if subcommand := lucidac.commands.get(ctx.invoked_subcommand, None):
        if subcommand.name == "monitor":
            reset = False

    if not fake:
        networks = []
        devices = []
        if not hosts:
            logger.warning(
                "Falling back to 0.0.0.0/0 zeroconf. Pass an explicit host or network with -h to silence this warning."
            )
            networks.append(ip_network("0.0.0.0/0"))
        for host in hosts:
            # Either one host was passed explicitly or we auto-detect via zeroconf
            if "/" not in host:
                devices.append((host, port, str(host)))
            else:
                networks.append(ip_network(host))
        for network in networks:
            logger.info("Searching for available network devices in %s...", network)
            devices = await detect_in_network(network)
            logger.info("Found network devices at %s.", devices)

        # Generate a controller and add devices
        controller = Controller(standalone=True)
        # await controller.start()
        for host, port, name in devices:
            await controller.add_device(host, port, name=name)
    else:
        controller = DummyController(standalone=True)

    # Put controller in context and make sure that we clean up after ourselves
    ctx.obj["controller"] = controller
    await ctx.with_async_resource(controller)

    # Unless chosen otherwise, reset the analog computer
    if reset:
        await controller.reset()

    # Create a run which is potentially modified by other commands (e.g. set-readout-elements)
    run_class = controller.get_run_implementation()
    ctx.obj["run"] = run_class()
    ctx.obj["previous_run"] = None

@lucidac.command()
@click.pass_obj
# Run options
@click.option("--op-time", type=int, default=None, help="OP time in nanoseconds.")
@click.option("--ic-time", type=int, default=None, help="IC time in nanoseconds.")
# Configuration options
@click.option("--config-file", "-c", type=click.File("r"), help="A config.json file to apply before starting the run.")
# Output options
@click.option("--output", "-o", type=click.File("wt"), default="-", help="File to write data to.")
@click.option(
    "--output-format",
    "-f",
    type=click.Choice(
        choices=(
            "none",
            "dat",
        )
    ),
    default="dat",
    help="Format to write data in.",
)
async def run(obj, op_time, ic_time, config_file: typing.TextIO, output, output_format):
    """
    Start a run (computation) and wait until it is complete.
    """
    controller: Controller = obj["controller"]
    run_: Run = obj["run"]

    # Read and send configuration
    config = json.load(config_file)
    if "00-00-00-00-00-00" in config.keys():
            config = config["00-00-00-00-00-00"]
    logger.debug("Setting controller configuration by circuit.")
    for protocol, managed_paths in controller.protocols.items():
        for carrier in list(controller.computer.carriers):
            if carrier.path in managed_paths:
                configure_carrier(config, carrier)
                await protocol.set_config(carrier)
    # await controller.forward_set_circuit(SetCircuitRequest(entity=Path(), config=config))

    # If the run in the context object is already done, we need a new one
    if run_.state.is_done():
        run_ = Run.make_from_other_run(run_)

    # Set run config
    if ic_time is not None:
        run_.config.ic_time = ic_time
    if op_time is not None:
        run_.config.op_time = op_time

    timeout = max(run_.config.op_time / 1_000_000_000 + 3, 3)
    run_ = obj["run"] = await controller.start_and_await_run(run_, timeout=timeout)
    if run_.state is RunState.ERROR:
        raise RunError("Error while executing run.")

    if output_format == "dat":
        exporter = DatExporter(output)
        exporter.export(run_)

for name, command in redac.commands.items():
    if name in ["hack", "proxy"] or name in lucidac.commands:
        continue
    lucidac.add_command(command, name)
# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import asyncio
import inspect
import logging
import os
from ipaddress import ip_network

import asyncclick as click

from pybrid.base.proto.io import ProtoIO
from pybrid.cli.base import cli
from pybrid.cli.base.commands import user_program
from pybrid.cli.dac import commands as _dac_commands
from pybrid.lucidac.controller import Controller as LUCIDACController
from pybrid.redac.controller import Controller as REDACController
from pybrid.redac.detect import detect_in_network
from pybrid.sim.controller import Controller as SimController

logger = logging.getLogger(__name__)

###
# Device initialization: LUCIDAC, REDAC, SIM prefixes
###


@cli.group()
@click.pass_context
@click.option(
    "--host",
    "-h",
    "hosts",
    type=str,
    required=False,
    multiple=True,
    help="Network name or address of the REDAC. Or address range to use for auto-detection.",
)
@click.option(
    "--port",
    "-p",
    type=int,
    default=5732,
    required=False,
    help="Network port of the REDAC.",
)
@click.option(
    "--reset/--no-reset",
    is_flag=True,
    default=True,
    show_default=True,
    help="Whether to reset the REDAC after connecting.",
)
async def redac(ctx: click.Context, hosts: list[str], port: int, reset: bool):
    """
    Entrypoint for all REDAC commands.

    Use :code:`pybrid redac --help` to list all available sub-commands.
    """
    bearer = os.getenv("PYBRID_AUTHENTICATION", None)
    if bearer is not None:
        logger.info("Using authentication bearer!")

    networks = []
    devices = []
    if not hosts:
        logger.warning(
            "Falling back to 0.0.0.0/0 zeroconf. Pass an explicit host or network with -h to silence this warning."
        )
        networks.append(ip_network("0.0.0.0/0"))
    for host in hosts:
        if "/" not in host:
            devices.append((host, port, str(host)))
        else:
            networks.append(ip_network(host))
    for network in networks:
        logger.info("Searching for available network devices in %s...", network)
        devices = await detect_in_network(network)
        logger.info("Found network devices at %s.", devices)

    controller = REDACController()
    for host, port, name in devices:
        await controller.add_device(host, port)

    ctx.obj["controller"] = controller
    await ctx.with_async_resource(controller)

    # Unless chosen otherwise, reset the analog computer
    if reset:
        await controller.reset()
    await asyncio.sleep(1)

    # Create a run which is potentially modified by other commands (e.g. set-readout-elements)
    run_class = controller.get_run_implementation()
    ctx.obj["run"] = run_class()
    ctx.obj["previous_run"] = None


@cli.group()
@click.pass_context
@click.option(
    "--host",
    "-h",
    type=str,
    default="localhost",
    required=False,
    help="Network name or address of the REDAC. Or address range to use for auto-detection.",
)
@click.option(
    "--port",
    "-p",
    type=int,
    default=5732,
    required=False,
    help="Network port of the REDAC.",
)
@click.option(
    "--entity",
    "-e",
    type=str,
    required=True,
    help="Path to entity definition, defining which hardware the simulator requires",
)
async def sim(ctx: click.Context, host: str, port: int, entity: str):
    """
    Entrypoint for all commands interacting with the simulator.

    Use :code:`pybrid redac --help` to list all available sub-commands.
    """
    bearer = os.getenv("PYBRID_AUTHENTICATION", None)
    if bearer is not None:
        logger.info("Using authentication bearer!")

    # Generate a controller and add devices
    controller = SimController()
    await controller.add_device(host, port, specification=ProtoIO.load_module(entity))

    # Put controller in context and make sure that we clean up after ourselves
    ctx.obj["controller"] = controller
    await ctx.with_async_resource(controller)

    # Create a run which is potentially modified by other commands (e.g. set-readout-elements)
    run_class = controller.get_run_implementation()
    ctx.obj["run"] = run_class()
    ctx.obj["previous_run"] = None


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
    default=False,
    show_default=True,
    help="Whether to reset the LUCIDAC after connecting.",
)
async def lucidac(ctx: click.Context, hosts: list[str], port: int, reset: bool):
    """
    Entrypoint for all LUCIDAC commands.

    Use :code:`pybrid lucidac --help` to list all available sub-commands.
    """
    networks = []
    devices = []
    if not hosts:
        logger.warning(
            "Falling back automatic LUCIDAC detection. Pass an explicit host or network with -h to silence this warning."
        )
        networks.append(ip_network("0.0.0.0/0"))
    for host in hosts:
        if "/" not in host:
            devices.append((host, port, str(host)))
        else:
            networks.append(ip_network(host))
    for network in networks:
        logger.info("Searching for available network devices in %s...", network)
        devices = await detect_in_network(network)
        logger.info("Found network devices at %s.", devices)

    controller = LUCIDACController()
    for host, port, device in devices:
        await controller.add_device(host, port)

    ctx.obj["controller"] = controller
    await ctx.with_async_resource(controller)

    if reset:
        await controller.reset()

    # Create a run which is potentially modified by other commands (e.g. set-readout-elements)
    run_class = controller.get_run_implementation()
    ctx.obj["run"] = run_class()
    ctx.obj["previous_run"] = None


###
# Register the subcommands defined in commands.py with each device group.
# Commands already attached to the top-level `cli` group (via @cli.command())
# are skipped here.
###

_TOP_LEVEL_COMMANDS = {"detect", "dummy", "proxy", "reset_usb"}

for _name, _obj in inspect.getmembers(_dac_commands):
    if not (hasattr(_obj, "callback") and hasattr(_obj, "params")):
        continue
    if isinstance(_obj, click.Group):
        continue
    if _name in _TOP_LEVEL_COMMANDS:
        continue
    redac.add_command(_obj)
    lucidac.add_command(_obj)
    sim.add_command(_obj)

# add imported commands
redac.add_command(user_program)
lucidac.add_command(user_program)
sim.add_command(user_program)

# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import asyncio
import inspect
import json
import logging
import os
import sys
import typing
import math
from ipaddress import ip_network
from typing import Callable

import asyncclick as click
from asyncclick import Choice
import matplotlib.pyplot as plt

import pybrid.base.proto.main_pb2 as pb
from pybrid.base.hybrid import EntityDoesNotExist
from pybrid.base.utils.json import LegacyConfigJSONParser
from pybrid.cli.base import cli
from pybrid.cli.base.commands import user_program
from pybrid.cli.base.shell import Shell
from pybrid.cli.dac.addressing import validate_and_map_config, parse_sync_impl
from pybrid.cli.dac.backend import expand_args, parse_backend_spec
from pybrid.redac.sync import SyncImplementationType
from pybrid.lucidac.controller import Controller as LUCIDACController
from pybrid.redac.blocks import SwitchingBlock
from pybrid.redac.cluster import Cluster
from pybrid.redac.controller import Controller as REDACController
from pybrid.redac.data import DatExporter
from pybrid.redac.detect import detect_in_network
from pybrid.redac.display import TreeDisplay
from pybrid.redac.dummy import DummyController
from pybrid.mock import DummyDAC, DummyDACConfig, DummyDACMacMode
from pybrid.redac.entities import Path, Entity
from pybrid.redac.monitor import Monitor
from pybrid.redac.run import Run, RunState, RunError
from pybrid.sim.controller import Controller as SimController
from pybrid.base.proto.io import ProtoIO
from pybrid.base.utils.addressing import Addressing, AddressingMap

# controls logging verbosity - use for debugging
# logging.basicConfig(level=logging.INFO)

logger = logging.getLogger(__name__)

###
# REDAC initialization
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
@click.option(
    "--fake",
    is_flag=True,
    default=False,
    show_default=True,
    help="Whether to fake any communication, allowing you to run without any computer present.",
)
@click.option(
    "--sync-impl",
    type=click.Choice(["native", "usbspi"]),
    default="native",
    required=False,
    show_default=True,
    help="Sync implementation strategy. 'native' uses the first mREDAC as sync master; 'usbspi' uses an external USB FTDI SPI device.",
)
@click.option(
    "--strict/--no-strict",
    is_flag=True,
    default=True,
    show_default=True,
    help="In strict mode, reject config files with virtual addresses. Use --no-strict to auto-map.",
)
@click.option(
    "--portable-map",
    type=click.Path(exists=True),
    default=None,
    required=False,
    help="JSON file mapping virtual MAC addresses to physical ones.",
)
async def redac(ctx: click.Context, hosts: list[str], port: int, reset: bool, fake: bool, sync_impl: str, strict: bool, portable_map: str | None):
    """
    Entrypoint for all REDAC commands.

    Use :code:`pybrid redac --help` to list all available sub-commands.
    """
    bearer = os.getenv("PYBRID_AUTHENTICATION", None)
    if bearer is not None:
        logger.info("Using authentication bearer!")

    # Some sub-commands may change default options
    # TODO: It would be cleaner to introduce a specialization of click.Group
    if subcommand := redac.commands.get(ctx.invoked_subcommand, None):
        if subcommand is monitor:
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
        controller = REDACController(sync_impl=parse_sync_impl(sync_impl))
        for host, port, name in devices:
            await controller.add_device(host, port, name=name)
    else:
        controller = DummyController()

    # Put controller in context and make sure that we clean up after ourselves
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
    ctx.obj["virtual_address_map"] = AddressingMap.map_redac
    ctx.obj["strict"] = strict
    ctx.obj["portable_map"] = portable_map

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
    "--strict/--no-strict",
    is_flag=True,
    default=True,
    show_default=True,
    help="In strict mode, reject config files with virtual addresses. Use --no-strict to auto-map.",
)
@click.option(
    "--portable-map",
    type=click.Path(exists=True),
    default=None,
    required=False,
    help="JSON file mapping virtual MAC addresses to physical ones.",
)
async def sim(ctx: click.Context, host: str, port: int, strict: bool, portable_map: str | None):
    """
    Entrypoint for all commands interacting with the simulator.

    Use :code:`pybrid redac --help` to list all available sub-commands.
    """
    bearer = os.getenv("PYBRID_AUTHENTICATION", None)
    if bearer is not None:
        logger.info("Using authentication bearer!")

    # Generate a controller and add devices
    controller = SimController(sync_impl=SyncImplementationType.NATIVE)
    await controller.add_device(host, port, name=host)

    # Put controller in context and make sure that we clean up after ourselves
    ctx.obj["controller"] = controller
    await ctx.with_async_resource(controller)

    # Create a run which is potentially modified by other commands (e.g. set-readout-elements)
    run_class = controller.get_run_implementation()
    ctx.obj["run"] = run_class()
    ctx.obj["previous_run"] = None
    ctx.obj["virtual_address_map"] = AddressingMap.map_redac
    ctx.obj["strict"] = strict
    ctx.obj["portable_map"] = portable_map

###
# LUCIDAC initialization
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
@click.option(
    "--fake",
    is_flag=True,
    default=False,
    show_default=True,
    help="Whether to fake any communication, allowing you to run without any computer present.",
)
@click.option(
    "--strict/--no-strict",
    is_flag=True,
    default=True,
    show_default=True,
    help="In strict mode, reject config files with virtual addresses. Use --no-strict to auto-map.",
)
@click.option(
    "--portable-map",
    type=click.Path(exists=True),
    default=None,
    required=False,
    help="JSON file mapping virtual MAC addresses to physical ones.",
)
async def lucidac(ctx: click.Context, hosts: list[str], port: int, reset: bool, fake: bool, strict: bool, portable_map: str | None):
    """
    Entrypoint for all LUCIDAC commands.

    Use :code:`pybrid lucidac --help` to list all available sub-commands.
    """

    # Some sub-commands may change default options
    # TODO: It would be cleaner to introduce a specialization of click.Group
    if subcommand := lucidac.commands.get(ctx.invoked_subcommand, None):
        if subcommand is monitor:
            reset = False

    if not fake:
        networks = []
        devices = []
        if not hosts:
            logger.warning(
                "Falling back automatic LUCIDAC detection. Pass an explicit host or network with -h to silence this warning."
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
        controller = LUCIDACController(sync_impl=SyncImplementationType.NATIVE)

        for host, port, device in devices:
            await controller.add_device(host, port, name=device)

        if reset:
            await controller.reset()
    else:
        controller = DummyController()

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
    ctx.obj["virtual_address_map"] = AddressingMap.map_lucistack
    ctx.obj["strict"] = strict
    ctx.obj["portable_map"] = portable_map

@click.command()
@click.pass_obj
@click.argument("path", type=str)
@click.argument("alias", type=str)
async def set_alias(obj, path, alias):
    """
    Define an alias for a path in an interactive session or script.
    You can use the alias in subsequent commands instead of a path argument.

    PATH is the path the alias should resolve to.
    ALIAS is the name of the alias.

    If '*' is passed for the path as first argument, the alias is set to point
    to the next carrier board which does not yet have an alias set for it.
    """
    controller: REDACController = obj["controller"]
    aliases: dict[str, Path] = obj.get("aliases", {})
    # Set alias supports a special '*' path as first argument,
    # in which case it selects the next carrier board which was not yet aliased.
    # This is used to not have to hard-code carrier board identifiers for (simple) examples.
    if path == "*":
        aliased_carrier_paths = {path for path in aliases.values() if path.depth == 1}
        for carrier in controller.computer.carriers:
            if carrier.path not in aliased_carrier_paths:
                path_ = carrier.path
                break
        else:
            raise EntityDoesNotExist("No more carrier boards available.")
    else:
        path_ = Path.parse(path, aliases=aliases)
    # Save alias
    if "aliases" not in obj:
        obj["aliases"] = dict()
    obj["aliases"].update({alias: path_})

@click.command()
@click.pass_obj
@click.option("--export", "-e", type=click.File("w"), default=None, required=False, help="File to export list of entities to.")
async def display(obj, export: typing.Optional[typing.TextIO]):
    """
    Display the hardware structure of the computer.
    """
    controller: REDACController = obj["controller"]
    click.echo(TreeDisplay().render(controller.computer))

    if export:
        export.write(json.dumps(controller._raw_entity_dict))

@click.command()
@click.pass_obj
@click.option("--export", "-e", type=str, default=None, required=False, help="Export device description to JSON or APB file")
async def describe(obj, export: str):
    """
    Retrieve a device's structure and store to file. Use, e.g. as target for the compiler.
    """
    from google.protobuf.json_format import MessageToDict, ParseDict, ParseError

    controller: REDACController = obj["controller"]
    descriptions = await controller.describe()

    # create protobuf file format for export
    file = pb.File()
    file.version.minor = 1
    for entity in descriptions.entities:
        file.device.entity.append(entity)

    if export:
        if export.endswith(".json"):
            with open(export, "w") as f:
                f.write(json.dumps(MessageToDict(file, preserving_proto_field_name=True), indent=2))
        elif export.endswith(".apb"):
            with open(export, "wb") as f:
                f.write(file.SerializeToString())
        else:
            click.echo("Unknown file format, supporting only .apb and .json format, exiting...")
    else:
        print(file)


@click.command()
@click.pass_obj
@click.option("--keep-calibration", type=bool, default=True, help="Whether to keep calibration.")
@click.option(
    "--sync/--no-sync",
    default=True,
    help="Whether to immediately sync configuration to hardware.",
)
async def reset(obj, keep_calibration, sync):
    """
    Reset the computer to initial configuration.
    """
    controller: REDACController = obj["controller"]
    await controller.reset(keep_calibration=keep_calibration, sync=sync)


@click.command()
@click.pass_obj
@click.option(
    "-r",
    "--recursive",
    type=bool,
    default=True,
    help="Whether to get status recursively for sub-entities.",
)
@click.argument("path", type=str)
async def get_entity_status(obj, recursive, path):
    """
    Get the status of an entity.

    PATH is the unique path of the entity.
    """
    controller: REDACController = obj["controller"]

    path_ = Path.parse(path, aliases=obj.get("aliases", None))
    entity = controller.computer.get_entity(path_)
    if not entity.path.depth == 1:
        raise NotImplementedError("Can only get the status of carrier boards currently.")

    status = await controller.get_status(entity, recursive=recursive)
    click.echo(status)

@click.command()
@click.pass_obj
async def get_system_temperatures(obj):
    controller: REDACController = obj["controller"]

    click.echo(await controller.get_system_temperatures())

@click.command()
@click.pass_context
@click.option("--output", "-o", type=click.File("wt"), default="-", help="File to write data to.")
async def monitor(ctx: click.Context, output):
    controller: REDACController = ctx.obj["controller"]

    click.echo("Starting monitor...")
    monitor_ = Monitor(controller, output)
    await ctx.with_async_resource(monitor_)

    click.echo("Press CTRL-C to stop.")
    try:
        while True:
            await asyncio.sleep(1)
    except (KeyboardInterrupt, asyncio.CancelledError):
        click.echo("Stopping monitor...")


@click.command()
@click.pass_obj
@click.option(
    "-r",
    "--recursive",
    type=bool,
    default=True,
    help="Whether to get config recursively for sub-entities.",
)
@click.argument("path", type=str)
async def get_entity_config(obj, recursive, path):
    """
    Get the configuration of an entity.

    PATH is the unique path of the entity.
    """
    controller: REDACController = obj["controller"]

    path_ = Path.parse(path, aliases=obj.get("aliases", None))
    entity = controller.computer.get_entity(path_)
    config = await controller.get_config(entity, recursive=recursive)
    click.echo(config)


@click.command()
@click.pass_obj
@click.option(
    "--sync/--no-sync",
    default=True,
    help="Whether to immediately send configuration to hybrid controller.",
)
@click.argument("path", type=str)
@click.argument("attribute", type=str)
@click.argument("value", type=str)
async def set_element_config(obj, sync, path, attribute, value):
    """
    Set one ATTRIBUTE to VALUE of the configuration of an entity at PATH.

    PATH is the unique path of the entity.
    ATTRIBUTE is the name of the attribute to change, e.g. 'factor'.
    VALUE is the new value of the attribute, e.g. '0.42'.
    """
    controller: REDACController = obj["controller"]

    path_ = Path.parse(path, aliases=obj.get("aliases", None))

    # Try to get the entity by its path
    entity: Entity = controller.computer.get_entity(path_)

    # Apply configuration to element
    entity.apply_partial_configuration(attribute, value)

    if sync:
        if path_.depth >= 4:
            # Element entities can not be configured directly, only via their parent
            entity = controller.computer.get_entity(path_.to_parent())
        await controller.set_config_request(controller.computer.build_config([entity]))


@click.command()
@click.pass_obj
@click.option(
    "--sync/--no-sync",
    default=True,
    help="Whether to immediately send configuration to hybrid controller.",
)
@click.option(
    "--force",
    is_flag=True,
    default=False,
    show_default=True,
    help="Force connection, possibly disconnecting existing connections.",
)
@click.argument("path", type=str)
@click.argument("connections", type=int, nargs=-1)
async def set_connection(obj, sync, force, path, connections):
    """
    Set one or multiple connections in a U-Block or I-Block.

    PATH is the unique path to either a U-Block or I-Block.
    CONNECTIONS specifies which connections should be set.
    For a U-Block, the syntax is <input> <output> [<output> ...].
    For a I-Block, the syntax is <input> [<input> ...] <output>.
    """
    controller: REDACController = obj["controller"]

    # Sanity check connections, which must be at least two arguments
    if len(connections) < 2:
        raise ValueError("You must supply at least two arguments for connection specification.")

    # Try to get the entity by its path
    path_ = Path.parse(path, aliases=obj.get("aliases", None))
    entity = controller.computer.get_entity(path_)
    # It must be a SwitchingBlock
    if not isinstance(entity, SwitchingBlock):
        raise ValueError("Expected a path to a SwitchingBlock.")

    # Set connection, data structure depends on block type
    entity.connect(*connections, force=force)

    # Send configuration
    if sync:
        await controller.set_config_request(controller.computer.build_config([entity]))


@click.command()
@click.pass_obj
@click.option(
    "--sync/--no-sync",
    default=True,
    help="Whether to immediately send configuration to hybrid controller.",
)
@click.argument("path", type=str)
@click.argument("m_out", type=int)
@click.argument("u_out", type=int)
@click.argument("c_factor", type=float)
@click.argument("m_in", type=int)
async def route(obj, sync, path, m_out, u_out, c_factor, m_in):
    """
    Route a signal on one cluster from one output of one M-Block through the U-Block, a coefficient on the C-Block,
    through the I-Block and back to one input of one M-Block.

    PATH is the unique path of the entity.
    M_OUT is the M-Block signal output index.
    U_OUT is the U-Block signal output index (equals coefficient index).
    C_FACTOR is the factor of the coefficient.
    M_IN is the M-Block signal input index (equals I-Block signal output index).
    """
    controller: REDACController = obj["controller"]

    # Try to get the entity by its path
    path_ = Path.parse(path, aliases=obj.get("aliases", None))
    cluster = controller.computer.get_entity(path_)
    # It must be a SwitchingBlock
    if not isinstance(cluster, Cluster):
        raise ValueError("Expected a path to a Cluster.")

    cluster.route(m_out, u_out, c_factor, m_in)
    if sync:
        await controller.set_config_request(controller.computer.build_config([cluster]))


@click.command()
@click.pass_obj
@click.option(
    "--sync/--no-sync",
    default=True,
    help="Whether to immediately send configuration to hybrid controller.",
)
@click.argument("path", type=str)
@click.argument("u_out", type=int)
@click.argument("c_factor", type=float)
@click.argument("m_in", type=int)
@click.argument("constant_value", type=float, default=1.0)
async def add_constant(obj, sync, path, u_out, c_factor, m_in, constant_value):
    """
    Inject a constant and add it to the math block input `m_in`.
    This replaces the b-group inputs in the U-block with constants, which limits some future connections.

    PATH is the unique path of the entity.
    U_OUT is the U-Block signal output index (equals coefficient index).
    C_FACTOR is the factor of the coefficient.
    M_IN is the M-Block signal input index (equals I-Block signal output index).
    """
    controller: REDACController = obj["controller"]

    # Try to get the entity by its path
    path_ = Path.parse(path, aliases=obj.get("aliases", None))
    cluster = controller.computer.get_entity(path_)
    # It must be a cluster
    if not isinstance(cluster, Cluster):
        raise ValueError("Expected a path to a Cluster.")

    cluster.add_constant(u_out, c_factor, m_in, constant_value=constant_value)
    if sync:
        await controller.set_config_request(controller.computer.build_config([cluster]))


@click.command()
@click.pass_obj
@click.option(
    "--sample-rate",
    "-r",
    type=Choice(
        [
            "1",
            "2",
            "4",
            "5",
            "8",
            "10",
            "16",
            "20",
            "25",
            "32",
            "40",
            "50",
            "64",
            "80",
            "100",
            "125",
            "160",
            "200",
            "250",
            "320",
            "400",
            "500",
            "625",
            "800",
            "1000",
            "1250",
            "1600",
            "2000",
            "2500",
            "3125",
            "4000",
            "5000",
            "6250",
            "8000",
            "10000",
            "12500",
            "15625",
            "20000",
            "25000",
            "31250",
            "40000",
            "50000",
            "62500",
            "100000",
            "125000",
            "200000",
            "250000",
            "500000",
            "1000000",
        ]
    ),
    required=False,
    help="Sample rate in samples/second.",
)
@click.option(
    "--num-channels",
    "-n",
    type=Choice(["0", "1", "2", "4", "8"]),
    default="0",
    help="Number of channels.",
)
@click.argument("paths", type=str, nargs=-1)
async def set_daq(obj, sample_rate: int, num_channels: int, paths: list[str]):
    """
    Configure data acquisition of subsequent run commands.
    Only useful in interactive sessions or scripts.
    Is lost once the session or script ends.
    """
    controller: REDACController = obj["controller"]
    run_: Run = obj["run"]

    run_.daq.num_channels = num_channels
    if sample_rate is not None:
        run_.daq.sample_rate = int(sample_rate)

    changed_entities = []
    for path in paths:
        path_ = Path.parse(path, aliases=obj.get("aliases", None))
        entity = controller.computer.get_entity(path_)
        changed_entities.extend(controller.computer.daq.capture(entity))

    for changed_entity in changed_entities:
        await controller.set_config_request(controller.computer.build_config([changed_entity]))

@click.command()
@click.pass_obj
# Run options
@click.option("--op-time", type=float, default=None, help="OP time in seconds.")
@click.option("--sample-rate", type=int, default=None, help="Sample rate in Hz.")
@click.option("--ic-time", type=int, default=None, help="IC time in nanoseconds.")
# Configuration options
@click.option("--config-file", "-c", type=str, help="Path to a config (.apb) file to set up the device and start the run.")
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
@click.option("--plot", 
    is_flag=True,
    default=False,
    show_default=True,
    help="Use matplotlib to draw a simple plot of the returned data")
async def run(obj, op_time: float, sample_rate: int, ic_time, config_file: str, output, output_format, plot):
    """
    Start a run (computation) and wait until it is complete. Wires the configuration
    to the device in RAW form, i.e. the user is responsible for its correctness.
    """
    controller: REDACController = obj["controller"]
    run_: Run = obj["run"]

    # load config and update to most recent version (if provided)
    # Build a single session for config + run
    session = controller.create_session()

    if config_file is not None:
        pb_file = ProtoIO.open_pb_file(config_file)

        strict = obj.get("strict", True)
        portable_map = obj.get("portable_map", None)
        address_map = obj["virtual_address_map"]

        # check if the controller has any physical addresses - if it has,
        # we should map virtual to physical addresses, e.g. in the case of directly
        # interacting with LUCIDACs
        device_has_physical_macs = [Addressing.is_physical_mac(c.path.to_carrier().to_mac())
            for c in controller.computer.carriers]

        if any(device_has_physical_macs) and not all(device_has_physical_macs):
            raise Exception("Mixing proxied and direct connections to LUCIDAC - please select only one mode.")

        if all(device_has_physical_macs):
            pb_file = validate_and_map_config(
                pb_file=pb_file,
                strict=strict,
                portable_map_path=portable_map,
                computer=controller.computer,
                address_map=address_map,
            )

        session.set_config_bundle(pb_file.bundle)
    else:
        logger.warning("NO config file provided, device will replay the last configuration...")

    # If the run in the context object is already done, we need a new one
    if run_.state.is_done():
        run_ = Run.make_from_other_run(run_)

    # Set run config
    if ic_time is not None:
        run_.config.ic_time = ic_time
    if op_time is not None:
        # needs to be set in nanoseconds
        run_.config.op_time = math.ceil(op_time * 1_000_000_000)
    if sample_rate is not None:
        run_.daq.sample_rate = sample_rate

    timeout = max(op_time + 3, 3)
    session.run(run_.config, daq=run_.daq, timeout=timeout)
    results = await session.execute()
    if results:
        run_ = results[0]
    obj["run"] = run_
    if run_.state is RunState.ERROR:
        raise RunError("Error while executing run.")

    # if output_format == "dat":
    #     exporter = DatExporter(output)
    #     exporter.export(run_)

    # Plot data if requested
    if plot:
        if run_.data:
            plt.figure(figsize=(10, 6))
            for channel_name, channel_data in run_.data.items():
                plt.plot(channel_data, label=str(channel_name))
            plt.xlabel('Sample Index')
            plt.ylabel('Value')
            plt.title('Run Data')
            plt.legend()
            plt.grid(True)
            plt.show()
        else:
            click.echo("No data available to plot.")


@click.command()
@click.pass_context
@click.option(
    "--ignore-errors",
    is_flag=True,
    default=False,
    show_default=True,
    help="Ignore errors while executing a script.",
)
@click.option(
    "--exit-after-script",
    "-x",
    is_flag=True,
    default=False,
    show_default=True,
    help="Exit after the scripts have been executed. Useful if output is piped into other programs.",
)
@click.argument("scripts", nargs=-1, type=click.File("r"))
async def shell(ctx: click.Context, ignore_errors, exit_after_script, scripts):
    """
    Start an interactive shell and/or execute a shell SCRIPT.

    SCRIPTS is a list of shell script files to execute before starting the interactive session."
    """
    computer_name = ctx.obj["controller"].computer.name

    # Create and start a shell
    shell_ = Shell(
        base_group=redac,
        base_ctx=ctx.parent,
        slug=computer_name,
        prompt=f"{computer_name} >> ",
    )
    with shell_:
        for script in scripts:
            logger.debug("Executing %s.", script.name)
            for line_no, line in enumerate(script):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                try:
                    await shell_.execute_cmdline(line)
                except Exception as exc:
                    logger.exception("Error in script during '%s' (line %s): %s", line, line_no, exc)
                    if not ignore_errors:
                        raise
        if not exit_after_script:
            await shell_.repl_loop()


@redac.group()
async def hack():
    """
    Collects 'hack' commands, for development purposes only.
    """
    pass


@click.command()
@click.pass_obj
@click.argument("input_file", type=click.File("r"))
@click.option("--output", "-o", type=str, multiple=True, required=True, help="Output file(s) for converted config. Can be specified multiple times.")
async def convert(obj, input_file: typing.TextIO, output: tuple[str]):
    """
    Convert a JSON-pb file from an old, nested JSON configuration

    Requires a device in order to parse and check the old config correctly.
    """

    controller: REDACController = obj["controller"]
    config_json = json.load(input_file)

    if ProtoIO.json_is_pb_file(config_json):
        raise Exception("convert() expects legacy-style JSON config files as input.")
    else:
        pb_file = LegacyConfigJSONParser.parse(config_json, controller.computer, True)

        # Write to each output file based on extension
        for output_path in output:
            if output_path.endswith(".json"):
                # Write as JSON
                output_json = ProtoIO.pbfile_to_json(pb_file)
                with open(output_path, "w") as f:
                    f.write(json.dumps(output_json, indent=2))
                    f.write("\n")
                click.echo(f"Converted config written to {output_path} (JSON format)")

            elif output_path.endswith(".apb"):
                # Write as binary protobuf
                with open(output_path, "wb") as f:
                    f.write(pb_file.SerializeToString())
                click.echo(f"Converted config written to {output_path} (APB format)")
            else:
                raise Exception(f"Unknown file extension for output '{output_path}'. Only .json and .apb are supported.")

@cli.command()
@click.pass_obj
async def detect(obj):
    """
    Detect devices in local network.
    """
    print("Detecting network devices...")
    for (host, port, name) in await detect_in_network(ip_network("0.0.0.0/0")):
        print(f"{host:15}:{port:4} {name}")


@cli.command()
@click.option(
    "--listen",
    "-l",
    type=str,
    default="0.0.0.0",
    show_default=True,
    help="Local bind address for the proxy server.",
)
@click.option(
    "--port",
    "-p",
    type=int,
    default=5732,
    show_default=True,
    help="Local port for the proxy server.",
)
@click.option(
    "--backend",
    "-b",
    type=str,
    multiple=True,
    required=True,
    help="Backend device address(es) in HOST[:PORT][/STACK/CARRIER] format. Accepts a single spec, a comma-separated list, or a path to a file with one spec per line. Can be specified multiple times.",
)
@click.option(
    "--session-timeout",
    type=float,
    default=10.0,
    show_default=True,
    help="Session idle timeout in seconds after a run completes.",
)
@click.option(
    "--auth/--no-auth",
    default=False,
    show_default=True,
    help="Enable proxy-level authentication (reads PYBRID_AUTHENTICATION env var).",
)
@click.option(
    "--debug",
    is_flag=True,
    default=False,
    show_default=True,
    help="Enable verbose debug logging (session lifecycle, run events, errors).",
)
async def proxy(listen: str, port: int, backend: tuple[str, ...], session_timeout: float, auth: bool, debug: bool):
    """
    Start a native C++ proxy server in front of one or more LUCIDAC devices.

    Clients connect to the proxy on LISTEN:PORT and are transparently
    forwarded to the backend devices. The proxy handles session management,
    describe caching, and multi-backend routing.

    Example usage:

        pybrid proxy -b 192.168.150.57 -b 192.168.150.58
        pybrid proxy -b 192.168.150.57/0/0,192.168.150.58/0/1
        pybrid proxy -b /path/to/backends.txt
        pybrid proxy -b 192.168.150.57:5732/0/0 -l 0.0.0.0 -p 5732
        pybrid proxy -b 192.168.150.57 --auth
    """
    try:
        from pybrid.native import ProxyServer
    except ImportError:
        click.echo("Error: Native C++ extension not available. Build pybrid-computing-native first.", err=True)
        raise SystemExit(1)

    raw_backends = expand_args(backend)
    if not raw_backends:
        click.echo("Error: No backend addresses resolved from the provided -b values.", err=True)
        raise SystemExit(1)

    specs = [parse_backend_spec(raw) for raw in raw_backends]

    has_any_location = any(s.stack is not None for s in specs)
    if not has_any_location:
        click.echo("Warning: Without REDAC addresses, all carriers will be treated equal. For LUCIDACs, you can safely ignore this warning. When using a REDAC, this means that pybrid will not be able to route signals automatically.")

    proxy_server = ProxyServer(auth)
    if debug:
        proxy_server.set_debug(True)

    for spec in specs:
        click.echo(f"Connecting to backend {spec.host}:{spec.port}...")
        proxy_server.add_backend(spec.host, spec.port, stack=spec.stack, carrier=spec.carrier)

    proxy_server.set_session_timeout(session_timeout)

    # Try to register the USBSPI sync callback. The FTDI SPI device must be
    # attached to the proxy machine (physically connected to the mREDACs).
    # If the device is not present, USBSPI sync is unavailable and only
    # NATIVE sync mode will work.
    try:
        from pybrid.redac.sync import Sync
        sync_device = Sync()
        proxy_server.set_sync_callback(sync_device.trigger)
        click.echo("USBSPI sync device detected and registered.")
    except Exception as exc:
        click.echo(f"No USBSPI sync device found ({exc}); only NATIVE sync available.")

    proxy_server.start(listen, port)

    actual_port = proxy_server.local_port()
    click.echo(f"Proxy server listening on {listen}:{actual_port}")
    click.echo(f"Backends: {len(specs)}, session timeout: {session_timeout}s")
    click.echo("Press Ctrl+C to stop.")

    try:
        while proxy_server.is_running():
            await asyncio.sleep(0.5)
    except (KeyboardInterrupt, asyncio.CancelledError):
        click.echo("\nShutting down proxy server...")
    finally:
        proxy_server.stop()
        click.echo("Proxy server stopped.")


@cli.command()
@click.option(
    "--host",
    "-h",
    type=str,
    default="0.0.0.0",
    show_default=True,
    help="Host address to bind the DummyDAC server to.",
)
@click.option(
    "--port",
    "-p",
    type=int,
    default=5732,
    show_default=True,
    help="Port to bind the DummyDAC server to.",
)
@click.option(
    "--virtual/--physical",
    default=True,
    show_default=True,
    help="Use virtual MACs (00-00-00-00-00-XX) or random physical MACs.",
)
async def dummy(host: str, port: int, virtual: bool):
    """
    Start a DummyDAC mock server for testing purposes.

    The DummyDAC simulates REDAC hardware and can be used for testing
    without physical hardware. It responds to the same protocol as
    real hardware.

    Example usage:

        pybrid dummy -h 0.0.0.0 -p 5732
        pybrid dummy --physical  # Use random MAC addresses
    """
    mac_mode = DummyDACMacMode.VIRTUAL if virtual else DummyDACMacMode.PHYSICAL
    config = DummyDACConfig(mac_mode=mac_mode)

    addr_method = "virtual" if virtual else "physical"
    click.echo(f"Starting DummyDAC server on {host}:{port} using {addr_method} addressing...")
    click.echo("Press Ctrl+C to stop.")

    async with DummyDAC(host, port, config) as server:
        # Keep the server running until interrupted
        try:
            while True:
                await asyncio.sleep(1)
        except (KeyboardInterrupt, asyncio.CancelledError):
            click.echo("\nShutting down DummyDAC server...")


###
# add all commands in this file to both groups (LUCIDAC, REDAC)
###

current_module = sys.modules[__name__]

for name, obj in inspect.getmembers(current_module):
    # Check if it's a Click command (has __click_params__ attribute)
    if hasattr(obj, 'callback') and hasattr(obj, 'params'):
        # Skip if it's a group (groups are also commands but we don't want them)
        if isinstance(obj, click.Group):
            continue

        # Skip top-level commands (already registered with cli group)
        if name in ['detect', 'dummy', 'proxy']:
            continue

        # Add the command to both groups
        redac.add_command(obj)
        lucidac.add_command(obj)
        sim.add_command(obj)

# add imported commands
redac.add_command(user_program)
lucidac.add_command(user_program)
sim.add_command(user_program)

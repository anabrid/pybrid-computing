# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import asyncio
import inspect
import json
import logging
import sys
import typing
from ipaddress import ip_network
from typing import TextIO

import asyncclick as click
from asyncclick import Choice
import matplotlib.pyplot as plt

import pybrid.base.proto.main_pb2 as pb
from pybrid.base.hybrid import EntityDoesNotExist
from pybrid.base.utils.json import JSONConfigAdapter
from pybrid.cli.base import cli
from pybrid.cli.base.commands import user_program
from pybrid.cli.base.shell import Shell
from pybrid.lucidac.controller import Controller as LUCIDACController
from pybrid.redac.blocks import SwitchingBlock
from pybrid.redac.cluster import Cluster
from pybrid.redac.controller import Controller as REDACController
from pybrid.redac.data import DatExporter
from pybrid.redac.detect import detect_in_network
from pybrid.redac.display import TreeDisplay
from pybrid.redac.dummy import DummyController
from pybrid.redac.entities import Path, Entity
from pybrid.redac.monitor import Monitor
from pybrid.redac.proxy import Proxy
from pybrid.redac.run import Run, RunState, RunError

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
    "--standalone/--no-standalone",
    is_flag=True,
    default=False,
    required=False,
    show_default=True,
    help="Run in standalone mode, which does not require an external super-controller or SYNC generator.",
)
async def redac(ctx: click.Context, hosts: list[str], port: int, reset: bool, fake: bool, standalone: bool):
    """
    Entrypoint for all REDAC commands.

    Use :code:`pybrid redac --help` to list all available sub-commands.
    """

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
        controller = REDACController(standalone=standalone)
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
    ctx.obj["use_virtual_macs"] = True

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
async def lucidac(ctx: click.Context, hosts: list[str], port: int, reset: bool, fake: bool, standalone: bool = True):
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
        controller = LUCIDACController(standalone=standalone)

        if len(devices) > 1:
            logger.warning("Multiple LUCIDACs found, using the first one - use options -h and -p to select a specific LUCIDAC.")

        host, port, name = devices[0]
        await controller.add_device(host, port, name=name)

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
    ctx.obj["use_virtual_macs"] = False

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
@click.option("--export", "-e", type=click.File("w"), default=None, help="File to export list of entities to.")
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
        await controller.set_config(entity)


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
        await controller.set_config(entity)


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
        await controller.set_config(cluster)


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
        await controller.set_config(cluster)


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
        await controller.set_config(changed_entity)

@click.command()
@click.pass_obj
# Run options
@click.option("--op-time", type=int, default=None, help="OP time in nanoseconds.")
@click.option("--sample-rate", type=int, default=None, help="Sample rate in Hz.")
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
@click.option("--plot", 
    is_flag=True,
    default=False,
    show_default=True,
    help="Use matplotlib to draw a simple plot of the returned data")
async def run(obj, op_time, sample_rate: int, ic_time, config_file: typing.TextIO, output, output_format, plot):
    """
    Start a run (computation) and wait until it is complete.
    """
    controller: REDACController = obj["controller"]
    run_: Run = obj["run"]
    use_virtual_macs : bool = obj["use_virtual_macs"]

    # Read and send configuration (as protobuf file)
    config = json.load(config_file)
    pb_config = JSONConfigAdapter.parse(config, controller.computer, use_virtual_macs)
    await controller.forward_set_config(pb.ConfigCommand(bundle=pb.ConfigBundle(configs=pb_config)))

    # If the run in the context object is already done, we need a new one
    if run_.state.is_done():
        run_ = Run.make_from_other_run(run_)

    # Set run config
    if ic_time is not None:
        run_.config.ic_time = ic_time
    if op_time is not None:
        run_.config.op_time = op_time
    if sample_rate is not None:
        run_.daq.sample_rate = sample_rate

    timeout = max(run_.config.op_time / 1_000_000_000 + 3, 3)
    run_ = obj["run"] = await controller.start_and_await_run(run_, timeout=timeout)
    if run_.state is RunState.ERROR:
        raise RunError("Error while executing run.")

    if output_format == "dat":
        exporter = DatExporter(output)
        exporter.export(run_)

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
redac.add_command(run)
lucidac.add_command(run)


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


@hack.command()
@click.pass_obj
@click.argument("path", type=str, required=False)
async def power_up(obj: dict, path: typing.Optional[str] = None):
    """
    Automate the current hack-power-up sequence,
    which is believed to be necessary to get the system in a fully functional state.
    """
    controller: REDACController = obj["controller"]

    if path is not None:
        path = Path.parse(path)

    for protocol, managed_paths in controller.protocols.items():
        if path is None or path in managed_paths:
            logger.info("Power cycling and then rebooting %s... Press CTRL+C to cancel.", managed_paths)
            await asyncio.sleep(3)
            logger.info("Putting it into standby...")
            await protocol.set_standby(True)
            await asyncio.sleep(2)
            logger.info("Ramping out of standby...")
            await protocol.set_standby(False, hack_pwm_ramp=True)
            await asyncio.sleep(2)
            logger.info("Rebooting firmware...")
            await protocol.sys_reboot()
            await asyncio.sleep(2)
            logger.info("Power-up sequence for %s done.", managed_paths)


@click.command()
@click.pass_obj
@click.option(
    "--map",
    "-m",
    "map_",
    type=click.File("r"),
    required=True,
    help="JSON file containing the mapping of 'XX-00-WW-00-00-NN' virtual mac addresses to real ones.",
)
@click.option(
    "--partitioning",
    "-p",
    "partitioning_",
    type=click.File("r"),
    required=True,
    help="JSON file containing the definition of the machine partitioning.",
)
@click.option("--partitioning-mode", type=str, default="device")
@click.argument("host", type=str, default="localhost")
@click.argument("port", type=int, default=5732)
async def proxy(obj: dict, map_: TextIO, partitioning_: TextIO, partitioning_mode: str, host: str, port: int):
    proxy = Proxy(
        controller=obj["controller"],
        host=host,
        port=port,
        mac_mapping=json.load(map_),
        partition_config=json.load(partitioning_),
        mode=partitioning_mode,
    )

    async with proxy as (proxy_, server):
        click.echo(f"Starting proxy on {proxy_.host}:{proxy_.port}... Press Ctrl+C to exit.")
        await server.serve_forever()

@cli.command()
@click.pass_obj
async def detect(obj):
    """
    Detect devices in local network.
    """
    print("Detecting network devices...")
    for (host, port, name) in await detect_in_network(ip_network("0.0.0.0/0")):
        print(f"{host:15}:{port:4} {name}")

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
        
        # Add the command to both groups
        redac.add_command(obj)
        lucidac.add_command(obj)

# add imported commands
redac.add_command(user_program)
lucidac.add_command(user_program)

# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import logging

import asyncclick as click
from asyncclick import Choice

from pybrid.base.hybrid import EntityDoesNotExist
from pybrid.base.transport import TCPTransport
from pybrid.cli.base import cli
from pybrid.cli.base.commands import user_program
from pybrid.cli.base.ressources import ManagedAsyncResource
from pybrid.cli.base.shell import Shell

from pybrid.redac.blocks import SwitchingBlock
from pybrid.redac.cluster import Cluster
from pybrid.redac.controller import Controller
from pybrid.redac.data import DatExporter
from pybrid.redac.display import TreeDisplay
from pybrid.redac.entities import Path, Entity
from pybrid.redac.protocol.protocol import Protocol
from pybrid.redac.run import Run, RunState, RunError

logger = logging.getLogger(__name__)


@cli.group()
@click.pass_context
@click.option('--host', '-h', type=str, required=False, help="Network name or address of the REDAC.")
@click.option('--port', '-p', type=int, default=5732, required=False, help="Network port of the REDAC.")
@click.option('--reset/--no-reset', is_flag=True, default=True, show_default=True,
              help="Whether to reset the REDAC after connecting.")
async def redac(ctx: click.Context, host, port, reset):
    """
    Entrypoint for all REDAC commands.

    Use :code:`pybrid redac --help` to list all available sub-commands.
    """

    # Generate a transport
    if host is not None and port is not None:
        transport_ = ctx.obj["transport"] = await TCPTransport.create(host, port)
    else:
        raise RuntimeError("No valid combination of transport options given.")

    # Generate a protocol
    protocol = await Protocol.create(transport_)

    # Generate a controller, which will also start the protocol
    controller = await Controller.create(protocol)
    ctx.obj["controller"] = await ctx.with_async_resource(ManagedAsyncResource(controller, 'start', 'stop'))

    # Unless chosen otherwise, reset the analog computer
    if reset:
        await controller.reset()

    # Create a run which is potentially modified by other commands (e.g. set-readout-elements)
    ctx.obj["run"] = await controller.create_run()
    ctx.obj["previous_run"] = None


@redac.command()
@click.pass_obj
@click.argument('path', type=str)
@click.argument('alias', type=str)
async def set_alias(obj, path, alias):
    """
    Define an alias for a path in an interactive session or script.
    You can use the alias in subsequent commands instead of a path argument.

    PATH is the path the alias should resolve to.
    ALIAS is the name of the alias.

    If '*' is passed for the path as first argument, the alias is set to point
    to the next carrier board which does not yet have an alias set for it.
    """
    controller: Controller = obj["controller"]
    aliases: dict[str, Path] = obj.get("aliases", {})
    # Set alias supports a special '*' path as first argument,
    # in which case it selects the next carrier board which was not yet aliased.
    # This is used to not have to hard-code carrier board identifiers for (simple) examples.
    if path == '*':
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


@redac.command()
@click.pass_obj
async def display(obj):
    """
    Display the hardware structure of the REDAC.
    """
    controller: Controller = obj["controller"]
    click.echo(TreeDisplay().render(controller.computer))


@redac.command()
@click.pass_obj
@click.option('--keep-calibration', type=bool, default=True, help='Whether to keep calibration.')
@click.option('--sync/--no-sync', default=True, help='Whether to immediately sync configuration to hardware.')
async def reset(obj, keep_calibration, sync):
    """
    Reset the REDAC to initial configuration.
    """
    controller: Controller = obj["controller"]
    await controller.reset(keep_calibration=keep_calibration, sync=sync)


@redac.command()
@click.pass_obj
@click.option('-r', '--recursive', type=bool, default=True, help='Whether to get config recursively for sub-entities.')
@click.argument('path', type=str)
async def get_entity_config(obj, recursive, path):
    """
    Get the configuration of an entity.

    PATH is the unique path of the entity.
    """
    controller: Controller = obj["controller"]

    path_ = Path.parse(path, aliases=obj.get("aliases", None))
    config = await controller.protocol.get_config(path_, recursive)
    click.echo(config)


@redac.command()
@click.pass_obj
@click.option('--sync/--no-sync', default=True, help='Whether to immediately send configuration to hybrid controller.')
@click.argument('path', type=str)
@click.argument('attribute', type=str)
@click.argument('value', type=str)
async def set_element_config(obj, sync, path, attribute, value):
    """
    Set one ATTRIBUTE to VALUE of the configuration of an entity at PATH.

    PATH is the unique path of the entity.
    ATTRIBUTE is the name of the attribute to change, e.g. 'factor'.
    VALUE is the new value of the attribute, e.g. '0.42'.
    """
    controller: Controller = obj["controller"]

    path_ = Path.parse(path, aliases=obj.get("aliases", None))

    # Try to get the entity by its path
    entity: Entity = controller.computer.get_entity(path_)

    # Apply configuration to element
    entity.apply_partial_configuration(attribute, value)

    # Build a configuration message to the parent block
    entity_config = entity.generate_partial_configuration(attribute)

    if sync:
        if path_.depth >= 4:
            await controller.protocol.set_config_request(entity=path_.parent,
                                                         config={"elements": {path_.id_: entity_config}})
        else:
            await controller.protocol.set_config_request(entity=path_, config=entity_config)


@redac.command()
@click.pass_obj
@click.option('--sync/--no-sync', default=True, help='Whether to immediately send configuration to hybrid controller.')
@click.option('--force', is_flag=True, default=False, show_default=True,
              help="Force connection, possibly disconnecting existing connections.")
@click.argument('path', type=str)
@click.argument('connections', type=int, nargs=-1)
async def set_connection(obj, sync, force, path, connections):
    """
    Set one or multiple connections in a U-Block or I-Block.

    PATH is the unique path to either a U-Block or I-Block.
    CONNECTIONS specifies which connections should be set.
    For a U-Block, the syntax is <input> <output> [<output> ...].
    For a I-Block, the syntax is <input> [<input> ...] <output>.
    """
    controller: Controller = obj["controller"]

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
        carrier = controller.computer.get_entity(path_.to_carrier())
        await controller.set_config(carrier)


@redac.command()
@click.pass_obj
@click.option('--sync/--no-sync', default=True, help='Whether to immediately send configuration to hybrid controller.')
@click.argument('path', type=str)
@click.argument('m_out', type=int)
@click.argument('u_out', type=int)
@click.argument('c_factor', type=float)
@click.argument('m_in', type=int)
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
    controller: Controller = obj["controller"]

    # Try to get the entity by its path
    path_ = Path.parse(path, aliases=obj.get("aliases", None))
    cluster = controller.computer.get_entity(path_)
    # It must be a SwitchingBlock
    if not isinstance(cluster, Cluster):
        raise ValueError("Expected a path to a Cluster.")

    cluster.route(m_out, u_out, c_factor, m_in)
    if sync:
        await controller.set_config(cluster)


@redac.command()
@click.pass_obj
@click.option('--sample-rate', '-r', type=Choice(
    ['1', '2', '4', '5', '8', '10', '16', '20', '25', '32', '40', '50', '64', '80', '100', '125', '160', '200', '250',
     '320', '400', '500', '625', '800', '1000', '1250', '1600', '2000', '2500', '3125', '4000', '5000', '6250', '8000',
     '10000', '12500', '15625', '20000', '25000', '31250', '40000', '50000', '62500', '100000', '125000', '200000',
     '250000', '500000', '1000000']), required=False, help="Sample rate in samples/second.")
@click.option('--num-channels', '-n', type=Choice(['0', '1', '2', '4', '8']), default='0', help="Number of channels.")
async def set_daq(obj, sample_rate, num_channels):
    """
    Configure data acquisition of subsequent run commands.
    Only useful in interactive sessions or scripts.
    Is lost once the session or script ends.
    """
    controller: Controller = obj["controller"]
    run_: Run = obj["run"]

    run_.daq.num_channels = num_channels
    if sample_rate is not None:
        run_.daq.sample_rate = int(sample_rate)


@redac.command()
@click.pass_obj
# Run options
@click.option('--op-time', type=int, default=None, help='OP time in nanoseconds.')
@click.option('--ic-time', type=int, default=None, help='IC time in nanoseconds.')
# Output options
@click.option('--output', '-o', type=click.File('wt'), default='-', help="File to write data to.")
@click.option('--output-format', '-f', type=click.Choice(choices=("none", "dat",)), default="dat",
              help="Format to write data in.")
async def run(obj, op_time, ic_time, output, output_format):
    """
    Start a run (computation) and wait until it is complete.
    """
    controller: Controller = obj["controller"]
    run_: Run = obj["run"]

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


@redac.command()
@click.pass_context
@click.option('--ignore-errors', is_flag=True, default=False, show_default=True,
              help="Ignore errors while executing a script.")
@click.option('--exit-after-script', '-x', is_flag=True, default=False, show_default=True,
              help="Exit after the scripts have been executed. Useful if output is piped into other programs.")
@click.argument('scripts', nargs=-1, type=click.File('r'))
async def shell(ctx: click.Context, ignore_errors, exit_after_script, scripts):
    """
    Start an interactive shell and/or execute a REDAC shell SCRIPT.

    SCRIPTS is a list of REDAC shell script files to execute before starting the interactive session."
    """
    computer_name = ctx.obj["controller"].computer.name

    # Create and start a shell
    shell_ = Shell(base_group=redac, base_ctx=ctx.parent, slug=computer_name, prompt=f"{computer_name} >> ")
    with shell_:
        for script in scripts:
            logger.debug("Executing %s.", script.name)
            for line_no, line in enumerate(script):
                line = line.strip()
                if not line or line.startswith('#'):
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
async def make_slave(obj):
    """
    Set one hybrid controller into slave mode.
    For development purposes only.
    """
    controller: Controller = obj["controller"]
    await controller.hack("slave", True)


redac.command()(user_program)

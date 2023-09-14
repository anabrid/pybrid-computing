# Copyright (c) 2022 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
#
# This file is part of the pyanabrid software packet.
#
# ANABRID_BEGIN_LICENSE:GPL
# Commercial License Usage
# Licensees holding valid commercial anabrid licenses may use this file in
# accordance with the commercial license agreement provided with the
# Software or, alternatively, in accordance with the terms contained in
# a written agreement between you and Anabrid GmbH. For licensing terms
# and conditions see https://www.anabrid.com/licensing. For further
# information use the contact form at https://www.anabrid.com/contact.
#
# GNU General Public License Usage
# Alternatively, this file may be used under the terms of the GNU
# General Public License version 3 as published by the Free Software
# Foundation and appearing in the file LICENSE.GPL3 included in the
# packaging of this file. Please review the following information to
# ensure the GNU General Public License version 3 requirements
# will be met: https://www.gnu.org/licenses/gpl-3.0.html.
# For Germany, additional rules exist. Please consult /LICENSE.DE
# for further agreements.
# ANABRID_END_LICENSE

import logging

import asyncclick as click
from pyanabrid.cli.base.ressources import ManagedAsyncResource

from pyanabrid.base.transport.network import TCPTransport
from pyanabrid.cli.base import cli
from pyanabrid.cli.base.shell import Shell

from pyanabrid.base.hybrid import EntityDoesNotExist
from pyanabrid.redac.blocks import SwitchingBlock
from pyanabrid.redac.cluster import Cluster
from pyanabrid.redac.controller import Controller
from pyanabrid.redac.display import TreeDisplay
from pyanabrid.redac.elements import ComputationElement
from pyanabrid.redac.entities import Path
from pyanabrid.redac.protocol.protocol import Protocol
from pyanabrid.redac.run import Run, RunState, RunError

logger = logging.getLogger(__name__)


@cli.group()
@click.pass_context
@click.option('--host', '-h', type=str, required=False)
@click.option('--port', '-p', type=int, required=False)
async def redac(ctx: click.Context, host, port):
    """
    Entrypoint for all REDAC commands.
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

    # Create a run which is potentially modified by other commands (e.g. set-readout-elements)
    ctx.obj["run"] = await controller.create_run()
    ctx.obj["previous_run"] = None


@redac.command()
@click.pass_obj
@click.argument('path', type=str)
@click.argument('alias', type=str)
async def set_alias(obj, path, alias):
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
    controller: Controller = obj["controller"]
    click.echo(TreeDisplay().render(controller.computer))


@redac.command()
@click.pass_obj
@click.option('-r', '--recursive', type=bool, default=True, help='Whether to get config recursively for sub-entities.')
@click.argument('path', type=str)
async def get_entity_config(obj, recursive, path):
    controller: Controller = obj["controller"]

    path_ = Path.parse(path, aliases=obj.get("aliases", None))
    config = await controller.protocol.get_config(path_, recursive)
    click.echo(config)


@redac.command()
@click.pass_obj
@click.argument('path', type=str)
@click.argument('attribute', type=str)
@click.argument('value', type=str)
async def set_element_config(obj, path, attribute, value):
    controller: Controller = obj["controller"]

    path_ = Path.parse(path, aliases=obj.get("aliases", None))
    if not path_.depth == 4:
        raise ValueError("This command currently expects a path of depth 4.")
    path_block = path_.parent

    # Try to get the entity by its path
    element: ComputationElement = controller.computer.get_entity(path_)

    # Apply configuration to element
    element.apply_partial_configuration(attribute, value)

    # Build a configuration message to the parent block
    element_config = element.generate_partial_configuration(attribute, value)

    await controller.protocol.set_config_request(entity=path_block, config={"elements": {path_.id_: element_config}})


@redac.command()
@click.pass_obj
@click.option('--force', is_flag=True, default=False, show_default=True)
@click.argument('path', type=str)
@click.argument('connections', type=int, nargs=-1)
async def set_connection(obj, force, path, connections):
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
    carrier = controller.computer.get_entity(path_.to_carrier())
    await controller.set_config(carrier)


@redac.command()
@click.pass_obj
@click.argument('path', type=str)
@click.argument('m_out', type=int)
@click.argument('u_out', type=int)
@click.argument('c_factor', type=float)
@click.argument('m_in', type=int)
async def route(obj, path, m_out, u_out, c_factor, m_in):
    controller: Controller = obj["controller"]

    # Try to get the entity by its path
    path_ = Path.parse(path, aliases=obj.get("aliases", None))
    cluster = controller.computer.get_entity(path_)
    # It must be a SwitchingBlock
    if not isinstance(cluster, Cluster):
        raise ValueError("Expected a path to a Cluster.")

    cluster.route(m_out, u_out, c_factor, m_in)
    await controller.set_config(cluster)


@redac.command()
@click.pass_obj
@click.option('--op-time', type=int, default=None, help='OP time in nanoseconds.')
@click.option('--ic-time', type=int, default=None, help='IC time in nanoseconds.')
async def run(obj, op_time, ic_time):
    controller: Controller = obj["controller"]
    run_: Run = obj["run"]

    # Set run config
    if ic_time is not None:
        run_.config.ic_time = ic_time
    if op_time is not None:
        run_.config.op_time = op_time

    run_ = obj["run"] = await controller.start_and_await_run(run_, timeout=max(run_.config.op_time/1_000_000_000+3, 3))
    if run_.state is RunState.ERROR:
        raise RunError("Error while executing run.")


@redac.command()
@click.pass_context
@click.option('--ignore-errors', is_flag=True, default=False, show_default=True)
@click.option('--exit-after-script', is_flag=True, default=False, show_default=True)
@click.argument('scripts', nargs=-1, type=click.File('r'))
async def shell(ctx: click.Context, ignore_errors, exit_after_script, scripts):
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

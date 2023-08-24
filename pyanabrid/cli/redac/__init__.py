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

from pyanabrid.redac.controller import Controller
from pyanabrid.redac.display import TreeDisplay
from pyanabrid.redac.entities import Path
from pyanabrid.redac.protocol.protocol import Protocol

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
async def display(obj):
    controller: Controller = obj["controller"]
    click.echo(TreeDisplay().render(controller.computer))


@redac.command()
@click.pass_obj
@click.option('-r', '--recursive', type=bool, default=True, help='Whether to get config recursively for sub-entities.')
@click.argument('path', type=str)
async def get_entity_config(obj, recursive, path):
    controller: Controller = obj["controller"]

    path_ = Path.parse(path)
    config = await controller.protocol.get_config(path_, recursive)
    click.echo(config)


@redac.command()
@click.pass_obj
@click.argument('path', type=str)
@click.argument('attribute', type=str)
@click.argument('value', type=str)
async def set_element_config(obj, path, attribute, value):
    controller: Controller = obj["controller"]

    path_ = Path.parse(path)
    if not path_.depth == 4:
        raise ValueError("This command currently expects a path of depth 4.")
    path_block = path_.parent

    # Try to get the entity by its path
    entity = controller.computer.get_entity(path_)

    # Build a configuration message to the parent block
    element_config = entity.generate_partial_configuration(attribute, value)

    await controller.protocol.set_config(entity=path_block, config={"elements": {path_.id_: element_config}})

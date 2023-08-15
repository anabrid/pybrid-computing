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
    ctx.obj["protocol"] = await ctx.with_async_resource(ManagedAsyncResource(protocol, 'start', 'stop'))


@redac.command()
@click.pass_obj
@click.argument('path', type=str, required=False)
@click.argument('config', type=str, required=False)
async def get_entity_config(obj, path, config):
    protocol: Protocol = obj["protocol"]
    from pyanabrid.redac.protocol.messages import GetConfigRequest
    response = await protocol.send_message_and_wait_response(GetConfigRequest(entity=["blubbla"]))
    print(repr(response))


@redac.command()
@click.pass_obj
@click.argument('path', type=str)
@click.argument('config', type=str)
async def set_entity_config(obj, path, config):
    pass

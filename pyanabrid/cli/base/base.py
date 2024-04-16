# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import logging

import asyncclick as click

from pyanabrid.base.utils.logging import set_pyanabrid_logging_level

logger = logging.getLogger(__name__)
logging.basicConfig(format="%(asctime)s.%(msecs)03d | %(levelname)s | %(module)s | %(message)s", datefmt="%S")


@click.group()
@click.pass_context
@click.option(
    "--log-level",
    type=click.Choice([l for l in logging._levelToName.values() if not l == "NOTSET"]),
    default=logging._levelToName[logging.INFO],
    help="Set all 'pyanabrid' loggers to the passed level."
)
async def cli(context: click.Context, log_level: str):
    """
    Entrypoint for all functions in the anabrid command line tool.

    Additional :code:`pyanabrid` packages hook new subcommands into this entrypoint.
    Please see their documentation for additional available commands.
    """
    # Prepare context for all plugins
    context.ensure_object(dict)
    # Set logging level of all loggers
    set_pyanabrid_logging_level(log_level)

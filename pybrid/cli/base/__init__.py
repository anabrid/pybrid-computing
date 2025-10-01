# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

from pybrid.cli.base.base import cli
from pybrid.cli.base.loader import load_cli_plugins


def entrypoint():
    load_cli_plugins()
    cli()

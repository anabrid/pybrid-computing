# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

from .base import cli
from .loader import load_cli_plugins


def entrypoint():
    load_cli_plugins()
    cli()

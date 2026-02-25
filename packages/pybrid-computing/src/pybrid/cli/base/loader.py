# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import importlib
import logging
import pkgutil

logger = logging.getLogger(__name__)


def load_cli_plugins():
    logger.debug("Loading CLI plugins...")
    cli_namespace = importlib.import_module("pybrid.cli")
    cli_plugins = pkgutil.iter_modules(
        cli_namespace.__path__, cli_namespace.__name__ + "."
    )
    for plugin in cli_plugins:
        # pybrid.cli.base itself is found this way, ignore it
        if plugin.name == "pybrid.cli.base":
            continue
        # Import the plugin module, which registers itself with the base cli object
        logger.debug("Loading CLI plugin: %s from %s", plugin.name, plugin)
        importlib.import_module(plugin.name)

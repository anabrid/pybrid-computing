# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import logging


def set_pybrid_logging_level(log_level):
    """
    Set the logging level for all pybrid loggers.

    Sets the level on the root logger, the 'pybrid' parent logger (so new
    child loggers inherit it), all existing pybrid.* loggers, and handlers.

    :param log_level: The log level name (e.g., "DEBUG", "INFO").
    """
    level_num = logging.getLevelName(log_level) if isinstance(log_level, str) else log_level

    # Set root logger and handler levels
    logging.root.setLevel(level_num)
    for handler in logging.root.handlers:
        handler.setLevel(level_num)

    # Set level on 'pybrid' logger so child loggers inherit it
    logging.getLogger("pybrid").setLevel(level_num)

    # Set level on all existing pybrid.* loggers
    for name in logging.root.manager.loggerDict:
        if name.startswith("pybrid"):
            logging.getLogger(name).setLevel(level_num)


def redirect_logger_stream_handlers(from_, to, logger_=None):
    if logger_ is None:
        logger_ = logging.root
    for handler in logger_.handlers:
        if isinstance(handler, logging.StreamHandler) and handler.stream == from_:
            handler.stream = to

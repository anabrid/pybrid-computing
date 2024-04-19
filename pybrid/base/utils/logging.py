# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import logging


def set_pybrid_logging_level(log_level):
    loggers = [
        logging.getLogger(name)
        for name in logging.root.manager.loggerDict
        if name.startswith("pybrid")
    ]
    for logger_ in loggers:
        logger_.setLevel(log_level)


def redirect_logger_stream_handlers(from_, to, logger_=None):
    if logger_ is None:
        logger_ = logging.root
    for handler in logger_.handlers:
        if isinstance(handler, logging.StreamHandler) and handler.stream == from_:
            handler.stream = to

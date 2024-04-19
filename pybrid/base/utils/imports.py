# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import importlib
import sys


def import_file_as_module(file, name):
    spec = importlib.util.spec_from_file_location('user_program', file)
    module = importlib.util.module_from_spec(spec)
    sys.modules["user_program"] = module
    spec.loader.exec_module(module)
    return module

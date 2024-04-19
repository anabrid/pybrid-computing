# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import asyncclick as click

from pybrid.base.hybrid import BaseController, BaseRun, RunEvaluateReconfigureLoop
from pybrid.base.utils.imports import import_file_as_module


@click.pass_obj
@click.option('--output', '-o', type=click.File('w'), default='-')
@click.argument('user_program_file', type=click.Path(exists=True, file_okay=True, dir_okay=False))
async def user_program(obj, output, user_program_file):
    controller: BaseController = obj["controller"]
    run_: BaseRun = obj["run"]

    # Load user program
    user_program_module = import_file_as_module(user_program_file, "user_program")
    user_program_class: RunEvaluateReconfigureLoop = user_program_module.UserProgram
    user_program_ = user_program_class(controller, run_, output=output)

    await user_program_.entrypoint()

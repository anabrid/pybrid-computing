# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later
import typing

from pybrid.base.hybrid import EntityDoesNotExist
from pybrid.base.hybrid.computer import AnalogComputer
from pybrid.base.hybrid.programs.base import MultipleRuns
from pybrid.base.hybrid.run import BaseRun


class StateInheritingRuns(MultipleRuns):

    def _next_configuration(self, run: BaseRun, computer: AnalogComputer, previous_runs: typing.List[BaseRun]):
        # Restore state from previous run as far as possible
        prev_run = previous_runs[-1]
        for path, value in prev_run.final_values.items():
            try:
                entity = computer.get_entity(path)
            except EntityDoesNotExist:
                pass
            else:
                if hasattr(entity, "ic"):
                    # Sign is negated because integrators invert
                    entity.ic = -value[0]
        return super()._next_configuration(run, computer, previous_runs)

# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

r"""
Run-Evaluate-Reconfigure-Loop
=============================

A typical hybrid computing process involves an iteration between digital and analog computations:
An initial configuration is applied to the analog computer and the analog computation is started.
The user waits for the result and evaluates or collects the data from the analog computation.
He then defines a new analog configuration for the next run and repeats the process as long as necessary.

For example parameter variation problems or iterative analog algorithms can be implemented in such a manner.
Since most of the necessary logic is very generic, the :code:`pybrid` package provides an abstraction
that takes care of most of the underlying work: The :code:`RunEvaluateReconfigureLoop` class.

The :code:`RunEvaluateReconfigureLoop` implements all necessary parts of the following process flow.
First the class is initialized and the user can provide additional code that is executed once in the beginning,
e.g. to initialize variables used later.
Then a user-supplied :code:`set config` function defines a configuration for the analog computer,
which is then applied by the generic process logic.
A run with this config is automatically started and the program waits until it is complete.
The result is collected from the analog computer and passed to a user-supplied :code:`evaluate` function.
Depending on its return value, the loop restarts from the beginning or ends.

You can execute a :code:`UserProgram` with the :code:`pybrid` command line tool.

.. code-block:: bash

    pybrid [...] recl path/to/user/program/file.py


Class Documentation
-------------------

"""

import logging

from .base import MultipleRuns

logger = logging.getLogger(__name__)


class RunEvaluateReconfigureLoop(MultipleRuns):
    """
    Run-Evaluate-Reconfigure-Loop Abstraction

    This class implements the typical process flow of a run-evaluate-reconfigure-loop.
    Users should inherit this class and overwrite the following function to inject their specific code.

    * :func:`~pybrid.base.hybrid.programs.recl.RunEvaluateReconfigureLoop.set_user_variables`
      for one-time initialization code
    * :func:`~pybrid.base.hybrid.programs.recl.RunEvaluateReconfigureLoop.initial_configuration`
      for configuring the first run
    * :func:`~pybrid.base.hybrid.programs.recl.RunEvaluateReconfigureLoop.next_configuration`
      for configuring the next run (except the first)
    * :func:`~pybrid.base.hybrid.programs.recl.RunEvaluateReconfigureLoop.run_done`
      for evaluating a completed run
    * :func:`~pybrid.base.hybrid.programs.recl.RunEvaluateReconfigureLoop.loop_done`
      for final evaluation or cleanup code
    """

    # This class is mostly obsolete, since it does not anything on top of its MultipleRuns base class.
    pass

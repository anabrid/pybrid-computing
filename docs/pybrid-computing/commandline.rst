Commandline Reference
=====================

.. click:: pybrid.cli.base.base:cli
   :prog: pybrid
   :nested: full



Custom subcommands
------------------

You can register your own subcommands with the command line interface to extend the available functionality.
This is for example useful, if you want to provide easy-to-use analog algorithms to people not familiar with programing.



Computer specific commands
--------------------------

As we have seen in the :doc:`quickstart` section, each supported analog computer registers their own set of subcommands
with the common :code:`pybrid` command line entrypoint.

:doc:`/redac/commandline`
    The REDAC analog computer uses the subcommand :code:`redac`.
    See the :doc:`/redac/commandline` for more information.

    .. code-block:: bash

        pybrid redac [...]

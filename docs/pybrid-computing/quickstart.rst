Quickstart
==========

After a successful :doc:`installation`, the quickest way to start with hybrid computing
is the :code:`anabrid` command line tool.
It will take care of the lower-level initialization and communication with your analog computer.
See below for some examples or read the :doc:`commandline` section.



Connecting to an Analog Computer
--------------------------------

Connect your analog computer to the computer on which you installed :code:`pybrid-computing`.
Depending on the type of analog computer, this will be different.
Follow the guide you received with your analog computer.

The :doc:`../redac/index` for example is connected via ethernet.
You will need to know the IP address of the analog computer in your network.



Starting an interactive shell
-----------------------------

With the information on how you connected your analog computer, you can start an interactive shell,
with which you can control it.
Each analog computer registers a subcommand with the common :code:`pybrid` command line tool.
You can check their respective commandline reference for more information.
For the :doc:`../redac/index` this subcommand is called :code:`redac`.

To start a shell on a REDAC analog computer with IP address :code:`10.42.0.2`, execute the following command.

.. code-block:: bash

    pybrid redac -h 10.42.0.2 shell

Inside the shell, you may use several commands to change the configuration of the analog computer
or start a computation (a so-called "run").

.. code-block:: bash

    REDAC >> set-element-config ... factor 0.7
    REDAC >> run
    # Run result
    # id_ = 1
    # created = 2022-12-20 15:16:09.241935
    # flag externally_halted = No
    # flag overloaded = No
    #
    # time  value   element state
    # ... data ...

The shell has auto completion so it's a great way to interactively explore your analog computer.

.. image:: images/shell-example.*

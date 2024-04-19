Installation
============

The `pybrid-computing` suite is a collection of several python namespace packages.
For most end-users, installing the :code:`pybrid-computing` meta package will install all necessary packages.
Additional functionality can be installed by specifying `extra package options`_, e.g. :code:`pybrid-computing[all]`,
but should be rarely necessary.

To install :code:`pybrid-computing` use :code:`pip`:


.. code-block:: bash

    pip install pybrid-computing



Using a virtual environment
---------------------------

It is generally a good idea to install python packages inside a `virtual environment`_,
where they are isolated from system-wide installations and easier to manage.
You can use a tool like `virtualenvwrapper`_ to help you or use the following built-in commands.

First, create a project folder in which we will work from now on.

.. code-block:: bash

    mkdir project_folder
    cd project_folder

Then initialize a virtual environment in a sub-folder called :code:`venv` (which will be created for you).
You can adapt the name, but will have to change later commands as necessary.

.. code-block:: bash

    python -m venv venv

You can now `activate` the virtualenv, which will change your shell's environment variables such that
the python binary and packages from the virtual environment are used.

.. code-block:: bash

    source /venv/bin/activate
    which python
    # should print [...]/venv/bin/python

Alternatively, you can specify the path the to virtual env binaries directly.

.. code-block:: bash

    ./venv/bin/python --version
    ./venv/bin/pip --version

Once the virtual environment is activated, you can use :code:`python` and :code:`pip` commands transparently.

.. code-block:: bash

    pip install pybrid-computing



Next Steps
----------

After successfully installing the :code:`pybrid-computing` package, these are some possible next steps:

:doc:`quickstart`
    Follow some quickstart examples to get going.



.. _virtual environment: https://peps.python.org/pep-0405/
.. _extra package options: https://peps.python.org/pep-0508/#extras
.. _virtualenvwrapper: https://virtualenvwrapper.readthedocs.io/en/latest/

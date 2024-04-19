REDAC Blocks and Configurations
===============================

This page describes all available hardware entities and their possible configurations.

The firmware on the hybrid controller accepts various JSON message structures
as part of the :class:`pybrid.redac.protocol.messages.SetConfigRequest` message, which are documented below.
Alternatively, you can find the full JSON schema in the firmware documentation.

Base Elements and Computations
------------------------------

All function blocks in the REDAC are made up of elements,
with each implementing one computation from the following list.
The list of elements contained on a function block together with the attributes of the computation define
which configuration parameters need to be sent to configure a function block (see below).

Please remember that in the REDAC, all summation is done implicitly by the :class:`pybrid.redac.blocks.IBlock`.

.. automodule:: pybrid.redac.computations
   :members: Integration, ScalarMultiplication, Multiplication

Function Blocks
---------------

The following function blocks are available.

.. MIntBlock

.. autoclass:: pybrid.redac.blocks.MIntBlock()

    .. autoattribute:: pybrid.redac.blocks.MIntBlock.elements
       :annotation:

The configuration can be set with a :class:`pybrid.redac.protocol.messages.SetConfigRequest` message
with :attr:`pybrid.redac.protocol.messages.SetConfigRequest.config` confirming to the JSON schema
as documented in the firmware documentation.

.. UBlock

.. autoclass:: pybrid.redac.blocks.UBlock()
   :members:

The configuration can be set with a :class:`pybrid.redac.protocol.messages.SetConfigRequest` message
with :attr:`pybrid.redac.protocol.messages.SetConfigRequest.config` confirming to the JSON schema
as documented in the firmware documentation.

.. CBlock

.. autoclass:: pybrid.redac.blocks.CBlock()
   :members: elements

The configuration can be set with a :class:`pybrid.redac.protocol.messages.SetConfigRequest` message
with :attr:`pybrid.redac.protocol.messages.SetConfigRequest.config` confirming to the JSON schema
as documented in the firmware documentation.

.. IBlock

.. autoclass:: pybrid.redac.blocks.IBlock()
   :members:

The configuration can be set with a :class:`pybrid.redac.protocol.messages.SetConfigRequest` message
with :attr:`pybrid.redac.protocol.messages.SetConfigRequest.config` confirming to the JSON schema
as documented in the firmware documentation.

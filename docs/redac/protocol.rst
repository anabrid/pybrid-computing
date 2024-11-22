REDAC Network Protocol
======================

.. automodule:: pybrid.redac.protocol


Shared Datatypes
----------------

The following data types are shared between several messages.

.. automodule:: pybrid.redac.run
   :members:
   :undoc-members:
   :exclude-members: DAQConfigurationNumChannels

.. automodule:: pybrid.redac.protocol.types
   :members:


Envelope
--------

.. autoclass:: pybrid.redac.protocol.envelope.Envelope
   :members:


Base Message Classes
--------------------

All messages are based on the :class:`pybrid.redac.protocol.messages.Message` base class.
Requests and responses have additional common functionality in the :class:`pybrid.redac.protocol.messages.Request`
and :class:`pybrid.redac.protocol.messages.Response` base classes respectively.

.. autoclass:: pybrid.redac.protocol.messages.Message
   :members: parse_obj, register_callback, json
.. autoclass:: pybrid.redac.protocol.messages.Request
   :members:
.. autoclass:: pybrid.redac.protocol.messages.Response
   :members:


Initialization
--------------

These messages are mostly used once during the initialization phase of the controller or the client library.

.. autoclass:: pybrid.redac.protocol.messages.GetEntitiesRequest
   :members:
.. autoclass:: pybrid.redac.protocol.messages.GetEntitiesResponse
   :members:


Session Management
------------------

To facilitate multi-user support and a minimum form of authentication without additional scheduling software (like SLURM),
your controller can be configured to require starting a session and reserving resources before any other command using
those resources can be executed.

.. autoclass:: pybrid.redac.protocol.messages.StartSessionRequest
   :members:
.. autoclass:: pybrid.redac.protocol.messages.StartSessionResponse
   :members:
.. autoclass:: pybrid.redac.protocol.messages.ResumeSessionRequest
   :members:
.. autoclass:: pybrid.redac.protocol.messages.ResumeSessionResponse
   :members:
.. autoclass:: pybrid.redac.protocol.messages.EndSessionRequest
   :members:
.. autoclass:: pybrid.redac.protocol.messages.EndSessionResponse
   :members:
.. autoclass:: pybrid.redac.protocol.messages.EntityReservationRequest
   :members:
.. autoclass:: pybrid.redac.protocol.messages.EntityReservationResponse
   :members:


Entity Configuration
--------------------

After potentially reserving certain entities for a session, it is usually necessary to configure them for an upcoming run.

.. autoclass:: pybrid.redac.protocol.messages.SetCircuitRequest
   :members:
.. autoclass:: pybrid.redac.protocol.messages.SetCircuitResponse
   :members:
.. autoclass:: pybrid.redac.protocol.messages.ResetCircuitRequest
   :members:
.. autoclass:: pybrid.redac.protocol.messages.ResetCircuitResponse
   :members:
.. autoclass:: pybrid.redac.protocol.messages.GetCircuitRequest
   :members:
.. autoclass:: pybrid.redac.protocol.messages.GetCircuitResponse
   :members:
.. autoclass:: pybrid.redac.protocol.messages.SetDAQRequest
   :members:
.. autoclass:: pybrid.redac.protocol.messages.SetDAQResponse
   :members:
.. autoclass:: pybrid.redac.protocol.messages.GetMetadataRequest
   :members:
.. autoclass:: pybrid.redac.protocol.messages.GetMetadataResponse
   :members:


Run Management
--------------

To start the analog computer with the previously set configuration, a run is started.
A hybrid computation may require multiple runs (e.g. to gather statistical data) that are executed during one session.

.. autoclass:: pybrid.redac.protocol.messages.StartRunRequest
   :members:
.. autoclass:: pybrid.redac.protocol.messages.StartRunResponse
   :members:
.. autoclass:: pybrid.redac.protocol.messages.CancelRunRequest
   :members:
.. autoclass:: pybrid.redac.protocol.messages.CancelRunResponse
   :members:
.. autoclass:: pybrid.redac.protocol.messages.RunDataMessage
   :members:
.. autoclass:: pybrid.redac.protocol.messages.RunStateChangeMessage
   :members:


Internal Messages
-----------------

Some messages are intended to be used in the internal communication between the hybrid controller
and the carrier boards.
For testing purposes, you can also generate and send them from the digital control computer.

.. autoclass:: pybrid.redac.protocol.messages.GetOverloadRequest
   :members:
.. autoclass:: pybrid.redac.protocol.messages.GetOverloadResponse
   :members:


Other Messages
--------------

Miscellaneous messages are documented below.

.. automodule:: pybrid.redac.protocol.messages
   :members:
   :exclude-members: GetEntitiesRequest, GetEntitiesResponse,
                     Message, Request, Response,
                     StartSessionRequest, StartSessionResponse, ResumeSessionRequest, ResumeSessionResponse, EndSessionRequest, EndSessionResponse, EntityReservationRequest, EntityReservationResponse,
                     SetCircuitRequest, SetCircuitResponse, ResetCircuitRequest, ResetCircuitResponse, GetCircuitRequest, GetCircuitResponse, SetDAQRequest, SetDAQResponse, GetMetadataRequest, GetMetadataResponse,
                     StartRunRequest, StartRunResponse, CancelRunRequest, CancelRunResponse, RunDataMessage, RunStateChangeMessage, GetOverloadRequest, GetOverloadResponse
   :undoc-members:

REDAC Network Protocol
======================

.. automodule:: pyanabrid.redac.protocol


Shared Datatypes
----------------

The following data types are shared between several messages.

.. automodule:: pyanabrid.redac.run
   :members:
   :undoc-members:
   :exclude-members: DAQConfigurationNumChannels

.. automodule:: pyanabrid.redac.protocol.types
   :members:


Envelope
--------

.. autoclass:: pyanabrid.redac.protocol.envelope.Envelope
   :members:


Base Message Classes
--------------------

All messages are based on the :class:`pyanabrid.redac.protocol.messages.Message` base class.
Requests and responses have additional common functionality in the :class:`pyanabrid.redac.protocol.messages.Request`
and :class:`pyanabrid.redac.protocol.messages.Response` base classes respectively.

.. autoclass:: pyanabrid.redac.protocol.messages.Message
   :members: parse_obj, register_callback, json
.. autoclass:: pyanabrid.redac.protocol.messages.Request
   :members:
.. autoclass:: pyanabrid.redac.protocol.messages.Response
   :members:


Initialization
--------------

These messages are mostly used once during the initialization phase of the controller or the client library.

.. autoclass:: pyanabrid.redac.protocol.messages.GetEntitiesRequest
   :members:
.. autoclass:: pyanabrid.redac.protocol.messages.GetEntitiesResponse
   :members:


Session Management
------------------

To facilitate multi-user support and a minimum form of authentication without additional scheduling software (like SLURM),
your controller can be configured to require starting a session and reserving resources before any other command using
those resources can be executed.

.. autoclass:: pyanabrid.redac.protocol.messages.StartSessionRequest
   :members:
.. autoclass:: pyanabrid.redac.protocol.messages.StartSessionResponse
   :members:
.. autoclass:: pyanabrid.redac.protocol.messages.EndSessionRequest
   :members:
.. autoclass:: pyanabrid.redac.protocol.messages.EndSessionResponse
   :members:
.. autoclass:: pyanabrid.redac.protocol.messages.EntityReservationRequest
   :members:
.. autoclass:: pyanabrid.redac.protocol.messages.EntityReservationResponse
   :members:


Entity Configuration
--------------------

After potentially reserving certain entities for a session, it is usually necessary to configure them for an upcoming run.

.. autoclass:: pyanabrid.redac.protocol.messages.SetConfigRequest
   :members:
.. autoclass:: pyanabrid.redac.protocol.messages.SetConfigResponse
   :members:
.. autoclass:: pyanabrid.redac.protocol.messages.GetConfigRequest
   :members:
.. autoclass:: pyanabrid.redac.protocol.messages.GetConfigResponse
   :members:
.. autoclass:: pyanabrid.redac.protocol.messages.SetDAQRequest
   :members:
.. autoclass:: pyanabrid.redac.protocol.messages.SetDAQResponse
   :members:
.. autoclass:: pyanabrid.redac.protocol.messages.GetMetadataRequest
   :members:
.. autoclass:: pyanabrid.redac.protocol.messages.GetMetadataResponse
   :members:


Run Management
--------------

To start the analog computer with the previously set configuration, a run is started.
A hybrid computation may require multiple runs (e.g. to gather statistical data) that are executed during one session.

.. autoclass:: pyanabrid.redac.protocol.messages.StartRunRequest
   :members:
.. autoclass:: pyanabrid.redac.protocol.messages.StartRunResponse
   :members:
.. autoclass:: pyanabrid.redac.protocol.messages.CancelRunRequest
   :members:
.. autoclass:: pyanabrid.redac.protocol.messages.CancelRunResponse
   :members:
.. autoclass:: pyanabrid.redac.protocol.messages.RunDataMessage
   :members:
.. autoclass:: pyanabrid.redac.protocol.messages.RunStateChangeMessage
   :members:


Internal Messages
-----------------

Some messages are intended to be used in the internal communication between the hybrid controller
and the carrier boards.
For testing purposes, you can also generate and send them from the digital control computer.

.. autoclass:: pyanabrid.redac.protocol.messages.GetOverloadRequest
   :members:
.. autoclass:: pyanabrid.redac.protocol.messages.GetOverloadResponse
   :members:


Other Messages
--------------

Miscellaneous messages are documented below.

.. automodule:: pyanabrid.redac.protocol.messages
   :members:
   :exclude-members: GetEntitiesRequest, GetEntitiesResponse,
                     Message, Request, Response,
                     StartSessionRequest, StartSessionResponse, EndSessionRequest, EndSessionResponse, EntityReservationRequest, EntityReservationResponse,
                     SetConfigRequest, SetConfigResponse, GetConfigRequest, GetConfigResponse, SetDAQRequest, SetDAQResponse, GetMetadataRequest, GetMetadataResponse,
                     StartRunRequest, StartRunResponse, CancelRunRequest, CancelRunResponse, RunDataMessage, RunStateChangeMessage, GetOverloadRequest, GetOverloadResponse
   :undoc-members:

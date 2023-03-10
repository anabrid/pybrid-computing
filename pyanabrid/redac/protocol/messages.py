# Copyright (c) 2022 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
#
# This file is part of the pyanabrid software packet.
#
# ANABRID_BEGIN_LICENSE:GPL
# Commercial License Usage
# Licensees holding valid commercial anabrid licenses may use this file in
# accordance with the commercial license agreement provided with the
# Software or, alternatively, in accordance with the terms contained in
# a written agreement between you and Anabrid GmbH. For licensing terms
# and conditions see https://www.anabrid.com/licensing. For further
# information use the contact form at https://www.anabrid.com/contact.
#
# GNU General Public License Usage
# Alternatively, this file may be used under the terms of the GNU
# General Public License version 3 as published by the Free Software
# Foundation and appearing in the file LICENSE.GPL3 included in the
# packaging of this file. Please review the following information to
# ensure the GNU General Public License version 3 requirements
# will be met: https://www.gnu.org/licenses/gpl-3.0.html.
# For Germany, additional rules exist. Please consult /LICENSE.DE
# for further agreements.
# ANABRID_END_LICENSE

import logging
import typing
from datetime import datetime

from pydantic import BaseModel, Field, UUID4

from ..entities import Path
from ..modules import Module, ModuleType
from ..run import RunConfig, RunState
from .types import SuccessInfo

logger = logging.getLogger(__name__)


# ██████   █████  ███████ ███████      ██████ ██       █████  ███████ ███████ ███████ ███████
# ██   ██ ██   ██ ██      ██          ██      ██      ██   ██ ██      ██      ██      ██
# ██████  ███████ ███████ █████       ██      ██      ███████ ███████ ███████ █████   ███████
# ██   ██ ██   ██      ██ ██          ██      ██      ██   ██      ██      ██ ██           ██
# ██████  ██   ██ ███████ ███████      ██████ ███████ ██   ██ ███████ ███████ ███████ ███████


class Message(BaseModel):
    """
    Base class for all messages.

    Serialization and deserialization is handled with the help of the :code:`pydantic` package.
    """

    @classmethod
    def parse_obj(cls, **data: dict) -> 'Message':
        """Parses data from `dict` or `json`-like and returns a message instance."""
        ...

    @classmethod
    def register_callback(cls, callback: typing.Callable) -> typing.Callable:
        """Register a callback for some :py:class:`Message` subclass, which is triggered when the respective message
        is received.

        :parameter callback: Function to register as callback
        :returns: The original function
        :Usage: Intended to be used as decorator:

            .. code-block::

                # Register callback triggered on e.g. an incoming RunStateChangeMessage
                @RunStateChangeMessage.register_callback
                def callback(self, msg: RunStateChangeMessage):
                    # do something with the message

        """
        ...


class Request(Message):
    """
    Base class for requests sent to the controller.

    .. uml::

       Client -> Controller: **Request(...)**
       Controller -> Client: Response(...)

    """
    @classmethod
    def get_expected_response_type(cls) -> typing.Type["Response"]:
        """The :py:class:`Response` subclass expected for the answer to this request."""
        ...


class Response(Message):
    """
    Base class for responses to a previous request.

    .. uml::

       Client -> Controller: Request(...)
       Controller -> Client: **Response(...)**

    """
    #: The :py:class:`Request` subclass to which this is the response
    response_for: typing.ClassVar[Request]

    @property
    def successful(self) -> bool:
        """Indicates whether the request was handled successfully"""
        return not bool(self.first_error)

    @property
    def first_error(self) -> typing.Optional[str]:
        """Error message of the first error that occurred when the request was handled.
        `None` if there was no error."""
        return None


# ██    ██ ████████ ██ ██      ██ ████████ ██    ██
# ██    ██    ██    ██ ██      ██    ██     ██  ██
# ██    ██    ██    ██ ██      ██    ██      ████
# ██    ██    ██    ██ ██      ██    ██       ██
#  ██████     ██    ██ ███████ ██    ██       ██


class PingRequest(Request):
    """
    A heartbeat request to check for controller status.
    The controller replies with a :py:class:`PongResponse` message.

    .. uml::

       Client -> Controller: **PingRequest(...)**
       Controller -> Client: PongResponse(...)

    """
    #: A timestamp used to synchronize client and controller clocks.
    now: datetime = Field(default_factory=datetime.utcnow)


class PongResponse(Response):
    """
    A heartbeat response to an incoming :py:class:`PingRequest` message.

    .. uml::

       Client -> Controller: PingRequest(...)
       Controller -> Client: **PongResponse(...)**

    """
    response_for = PingRequest
    #: A timestamp used to synchronize client and controller clocks.
    #: The controller returns its timestamp so the client can check if it was applied correctly.
    now: datetime = Field(default_factory=datetime.utcnow)


# ██ ███    ██ ██ ████████ ██  █████  ██      ██ ███████  █████  ████████ ██  ██████  ███    ██
# ██ ████   ██ ██    ██    ██ ██   ██ ██      ██    ███  ██   ██    ██    ██ ██    ██ ████   ██
# ██ ██ ██  ██ ██    ██    ██ ███████ ██      ██   ███   ███████    ██    ██ ██    ██ ██ ██  ██
# ██ ██  ██ ██ ██    ██    ██ ██   ██ ██      ██  ███    ██   ██    ██    ██ ██    ██ ██  ██ ██
# ██ ██   ████ ██    ██    ██ ██   ██ ███████ ██ ███████ ██   ██    ██    ██  ██████  ██   ████


class GetEntitiesRequest(Request):
    """
    A request for the list of entity types (:py:class:`pyanabrid.redac.entities.EntityType`)
    by their path (:class:`pyanabrid.redac.entities.Path`).
    The controller responds with a :py:class:`GetEntitiesResponse` containing a tree-like representation of all entities.

    The :class:`GetEntitiesResponse` tells you the current assembly structure of the analog computer.
    Use a series of :class:`GetEntityConfiguration` messages if you also need to know the current configuration.

    .. uml::

       Client -> Controller: **GetEntitiesRequest()**
       activate Controller
       note over Controller: scans modules
       Controller -> Client: GetEntitiesResponse()
       deactivate Controller

    """
    pass


class GetEntitiesResponse(Response):
    """
    A response containing the list of modules (:py:class:`pyanabrid.redac.modules.ModuleType`) governed by the controller.

    .. uml::

       Client -> Controller: GetEntitiesRequest()
       activate Controller
       note over Controller: scans modules
       Controller -> Client: **GetEntitiesResponse()**
       deactivate Controller

    """
    response_for = GetEntitiesRequest
    #: A tree-like dictionary structure containing entity type information by path.
    entities: dict[Path, dict]


# ███████ ███████ ███████ ███████ ██  ██████  ███    ██
# ██      ██      ██      ██      ██ ██    ██ ████   ██
# ███████ █████   ███████ ███████ ██ ██    ██ ██ ██  ██
#      ██ ██           ██      ██ ██ ██    ██ ██  ██ ██
# ███████ ███████ ███████ ███████ ██  ██████  ██   ████


class StartSessionRequest(Request):
    """
    Request to start a session for which the requested elements are reserved.
    No other client can request those elements until the session is ended.

    Starting and managing sessions is only necessary if your controller is configured to require it.

    .. uml::

        participant "Client A" as C1
        participant "Client B" as C2
        participant "Controller" as CTRL

        C1 -> CTRL: StartSessionRequest(entities=[<X>, <Y>])
        CTRL -> C1: StartSessionResponse(id_=<secret>, success=True)
        ...during active session of Client A...
        C2 -> CTRL: StartSessionRequest(entities=[<X>, <Z>])
        CTRL -> C2: StartSessionResponse(success=False, error="X reserved.")
        ...
        C1 -> CTRL: EndSessionRequest(id_=<secret>)
        CTRL -> C1: EndSessionResponse(success=True)

    """
    #: A list of analog entities to reserve for this session.
    entities: list[Path]


class StartSessionResponse(Response):
    """
    Response to a prior :class:`StartSessionRequest`.

    If the reservation was successful, a secret ID is returned.
    This ID is used in subsequent configuration and run requests to authorize their usage of reserved entities.

    If not all requested entities could be reserved for the new session, the session is not started.
    """
    response_for = StartSessionRequest
    #: Secret session ID or None if the session could not be started.
    id_: typing.Optional[UUID4]
    #: Whether the session could be started and optional error info.
    success: SuccessInfo


class EndSessionRequest(Request):
    """
    Request to end a session.

    If there are any ongoing runs in the session, they are canceled first and any messages related to them are sent
    first by the controller, before the corresponding :class:`EndSessionResponse` is sent.

    Inactive sessions may be ended automatically depending on controller configuration.

    .. uml::

        participant "Client" as C
        participant "Controller" as CTRL

        C -> CTRL: EndSessionRequest(id_=<secret>)
        activate CTRL
        alt if ongoing requests
            note over CTRL: cancels any ongoing runs in this session
            CTRL -> C: RunStateChangeMessage(new=ERROR, ...)
        end
        CTRL -> C: EndSessionResponse(success=True)
        deactivate CTRL

    """
    #: The secret session ID to end.
    id_: UUID4


class EndSessionResponse(Response):
    """
    Response to a prior :class:`EndSessionRequest`.
    """
    #: Whether the session could be ended and optional error info. Usually True.
    success: SuccessInfo


class EntityReservationRequest(Request):
    """
    Request to reserve additional entities for an existing session.
    """
    #: Secret session ID
    id_: UUID4
    #: A list of analog entities to reserve for this session.
    entities: list[Path]


class EntityReservationResponse(Response):
    """
    Response to a prior :class:`EntityReservationRequest`.
    """
    #: Whether the requested entities were reserved and error information if they were not.
    success: SuccessInfo


#  ██████  ██████  ███    ██ ███████ ██  ██████  ██    ██ ██████   █████  ████████ ██  ██████  ███    ██
# ██      ██    ██ ████   ██ ██      ██ ██       ██    ██ ██   ██ ██   ██    ██    ██ ██    ██ ████   ██
# ██      ██    ██ ██ ██  ██ █████   ██ ██   ███ ██    ██ ██████  ███████    ██    ██ ██    ██ ██ ██  ██
# ██      ██    ██ ██  ██ ██ ██      ██ ██    ██ ██    ██ ██   ██ ██   ██    ██    ██ ██    ██ ██  ██ ██
#  ██████  ██████  ██   ████ ██      ██  ██████   ██████  ██   ██ ██   ██    ██    ██  ██████  ██   ████


class SetConfigRequest(Request):
    """
    A request to the controller to set a configuration for an entity.
    The controller forwards the request to the carrier board on which the entity is located
    and forwards its :class:`SetConfigResponse` response back.

    .. uml::

        participant "Client" as C
        participant "Controller" as CTRL
        participant "Carrier Board\\n(00:00:5e:00:53:af, )" as CB
        participant "Entity\\n(00:00:5e:00:53:af, 7, 42)" as E

        C -> CTRL: SetConfigRequest(\\n  entity=(00:00:5e:00:53:af, 7, 42), ...\\n)
        activate CTRL
        CTRL -> CB: SetConfigRequest(entity=(7, 42), ...)
        activate CB
        CB <-> E: <entity specific data via SPI>
        CTRL <- CB: SetConfigResponse(...)
        deactivate CB
        C <- CTRL: SetConfigResponse(...)
        deactivate CTRL
    """
    #: The entity to configure.
    entity: Path
    #: The configuration to apply.
    #: The data schema of the configuration depends on the type of entity.
    config: dict

    @classmethod
    def make(cls, entity):
        """Factory method to create a config request for some entity."""
        ...


class SetConfigResponse(Response):
    """A response to :py:class:`SetConfigRequest` conveying the success of the latter.

    .. uml::

           Client -> Controller: SetConfigRequest(...)
           activate Controller
           note over Controller: sets module config
           Controller -> Client: **SetConfigResponse**(...)
           deactivate Controller
    """
    response_for = SetConfigRequest
    success: SuccessInfo


class GetConfigRequest(Request):
    """
        A request to the controller to retrieve an element configuration for a some module.
        The controller responds with a :py:class:`GetConfigResponse`.

        .. uml::

           Client -> Controller: **GetConfigRequest**(...)
           activate Controller
           note over Controller: gets module config
           Controller -> Client: GetConfigResponse(...)
           deactivate Controller
    """
    #: Path to the entity of which the configuration should be returned.
    entity: Path


class GetConfigResponse(Response):
    """A response to :py:class:`GetConfigRequest` conveying the configuration of some entity.

    .. uml::

           Client -> Controller: GetConfigRequest(..)
           activate Controller
           note over Controller: gets module config
           Controller -> Client: **GetConfigResponse**(...)
           deactivate Controller
    """
    response_for = GetConfigRequest
    #: Path to the entity of which the configuration is returned.
    entity: Path
    #: The configuration of the entity.
    #: The data schema of the configuration depends on the type of entity.
    config: dict


class SetDAQRequest(Request):
    """A request to the controller to set a :py:class:`DAQConfiguration` determining how and when data should be
    acquired. The controller will respond with a :py:class:`SetDAQResponse`

    .. uml::

           Client -> Controller: **SetDAQRequest**(...)
           Controller -> Client: SetDAQResponse(...)
    """
    #: Paths of elements that should be sampled (can only contain paths to analog computation elements)
    paths: list[Path]
    #: Whether to sample during IC
    sample_ic: bool = False
    #: Whether to sample during OP
    sample_op: bool = True
    #: Whether to sample during OP_END
    sample_op_end: bool = True


class SetDAQResponse(Response):
    """A response to :py:class:`SetDAQRequest` conveying the success of the latter

    .. uml::

           Client -> Controller: SetDAQRequest(...)
           Controller -> Client: **SetDAQResponse**(...)
    """
    response_for = SetDAQRequest
    __root__: typing.Union[
        SuccessInfo, typing.List[typing.Union[SuccessInfo, typing.Dict]]
    ]


# ██████  ██    ██ ███    ██
# ██   ██ ██    ██ ████   ██
# ██████  ██    ██ ██ ██  ██
# ██   ██ ██    ██ ██  ██ ██
# ██   ██  ██████  ██   ████


class StartRunRequest(Request):
    """
    A request to start a run (computation).

    .. uml::

       Client -> Controller: **StartRunRequest()**
       alt run is accepted
         Controller -> Client: StartRunResponse(accepted=True)
       else run is not accepted (e.g. analog computer is busy or in failure mode)
         Controller -> Client: StartRunResponse(accepted=False)
       end
       
    """
    #: An ID that should be applied to the run.
    id_: int
    #: A :py:class:`pyanabrid.redac.run.RunConfig` that should be applied to the run.
    config: RunConfig

    @classmethod
    def from_run(cls, run):
        """
        Generate a :py:class:`pyanabrid.redac.protocol.messages.StartRunRequest`
        from a :py:class:`pyanabrid.redac.run.Run` instance.

        :param run: A run
        :return: A StartRunRequest instance
        """
        ...


class StartRunResponse(Response):
    """
        A response to a :py:class:`StartRunRequest`

        .. uml::

           Client -> Controller: StartRunRequest()
           alt run is accepted
             Controller -> Client: **StartRunResponse**(accepted=True)
           else run is not accepted (e.g. analog computer is busy or in failure mode)
             Controller -> Client: **StartRunResponse**(accepted=False)
           end

    """
    response_for = StartRunRequest
    #: Whether the run request was accepted
    accepted: bool


class RunStateChangeMessage(Message):
    """ Message from the controller that its :py:class:`RunState` changed

    .. uml::

           Client -> Controller: StartRunRequest()
           Controller -> Client: StartRunResponse(accepted=True)
           Controller -> Client: **RunStateChangeMessage**(old=QUEUE, new=TAKE_OFF)
           Controller --> Client: Some more run state messages...
           activate Controller
           loop
             Controller -> Client: RunDataMessage()
           end
           deactivate Controller
           note right : running
           Controller --> Client: Some more run state messages...
           Controller -> Client: **RunStateChangeMessage**(new=DONE)
    """
    #: ID of the run
    run_id: int
    #: Current time
    t: int
    #: Previous state
    old: RunState
    #: New state
    new: RunState
    #: Whether we are currently in overload
    overload: bool = False
    #: Whether external halt is currently active
    external_halt: bool = False


class RunDataMessage(Message):
    """ Message from the controller containing run data acquired

        .. uml::

               Client -> Controller: StartRunRequest()
               Controller -> Client: StartRunResponse(accepted=True)
               Controller --> Client: Some run state messages...
               activate Controller
               loop
                 Controller -> Client: **RunDataMessage**()
               end
               deactivate Controller
               note right : running
               Controller --> Client: Some run state messages...
    """
    #: ID of the run
    run_id: int
    #: Current state of the run
    state: RunState
    #: Time of the first datapoint in `data`
    t_0: int
    #: Index of the first datapoint in `data`
    idx_0: int
    #: Acquired data, normalized to [-1,+1]
    data: typing.List[float]

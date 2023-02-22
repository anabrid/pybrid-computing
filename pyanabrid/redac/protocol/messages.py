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

from pydantic import BaseModel, Field, ValidationError

from ..entities import Path
from ..modules import Module, ModuleType
from ..run import RunConfig, RunState
from .types import SuccessInfo

logger = logging.getLogger(__name__)


class Message(BaseModel):
    """Base class for messages"""

    @classmethod
    def parse_obj(cls, *args, **kwargs):
        """Parses object from `dict` or `json`-like"""
        ...

    @classmethod
    def register_callback(cls, callback):
        """Register a callback for some :py:class:`Message` subclass, which is triggered when the respective message
        is received.

        :Usage: Intended to be used as decorator

            .. code-block::

                @RunStateChangeMessage.register_callback  # or any other Message subclass
                def callback(self, msg: RunStateChangeMessage):
                    # do something with the message

        """
        ...


class Request(Message):
    """Base class for requests sent to the controller

    .. uml::

       Client -> Controller: **Request()**
       Controller -> Client: Response()

    """
    @classmethod
    def get_expected_response_type(cls) -> typing.Type["Response"]:
        """Type of the :py:class:`Response` subclass expected for this request"""
        return _EXPECTED_RESPONSE_CLASS_MAP[cls]


class Response(Message):
    """Base class for responses received from the controller

    .. uml::

       Client -> Controller: Request()
       Controller -> Client: **Response()**

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


class PingRequest(Request):
    """
    A heartbeat request to check for controller status.
    The controller replies with a :py:class:`PongResponse` message.

    .. uml::

       Client -> Controller: **PingRequest()**
       Controller -> Client: PongResponse()

    """
    #: A timestamp used to synchronize client and controller clocks.
    now: datetime = Field(default_factory=datetime.utcnow)


class PongResponse(Response):
    """
    A heartbeat response to an incoming :py:class:`PingRequest` message.

    .. uml::

       Client -> Controller: PingRequest()
       Controller -> Client: **PongResponse()**

    """
    response_for = PingRequest
    #: A timestamp used to synchronize client and controller clocks.
    #: The controller returns its timestamp so the client can check if it was applied correctly.
    now: datetime = Field(default_factory=datetime.utcnow)


class GetModulesRequest(Request):
    """A request for the list of modules (:py:class:`pyanabrid.modelone.modules.ModuleType`) governed by the
    controller. The controller responds with a :py:class:`GetModulesResponse`.

    .. uml::

       Client -> Controller: **GetModulesRequest()**
       activate Controller
       note over Controller: scans modules
       Controller -> Client: GetModulesResponse()
       deactivate Controller

    """
    pass


class GetModulesResponse(Response):
    """A response containing the list of modules (:py:class:`pyanabrid.modelone.modules.ModuleType`) governed by the
        controller.

        .. uml::

           Client -> Controller: GetModulesRequest()
           activate Controller
           note over Controller: scans modules
           Controller -> Client: **GetModulesResponse()**
           deactivate Controller

        """
    response_for = GetModulesRequest
    __root__: typing.Dict[str, ModuleType]


class SetConfigDict(BaseModel):
    """:meta private:"""
    module: str
    elements: typing.List[typing.Dict]


class SetConfigRequest(Request):
    """
    A request to the controller to set an element configuration for a some module.
    The controller responds with a :py:class:`SetConfigResponse`.

    .. uml::

           Client -> Controller: **SetConfigRequest**()
           activate Controller
           note over Controller: sets module config
           Controller -> Client: SetConfigResponse()
           deactivate Controller
    """
    __root__: SetConfigDict

    @classmethod
    def make(cls, module: Module):
        """Factory method to create a config request for some module"""
        ...


class SetConfigResponse(Response):
    """A response to :py:class:`SetConfigRequest` conveying the success of the latter.

    .. uml::

           Client -> Controller: SetConfigRequest()
           activate Controller
           note over Controller: sets module config
           Controller -> Client: **SetConfigResponse**()
           deactivate Controller
    """
    response_for = SetConfigRequest
    __root__: SuccessInfo


class GetConfigDict(BaseModel):
    """:meta private:"""
    elements: typing.List[typing.Dict]


class GetConfigRequest(Request):
    """
        A request to the controller to retrieve an element configuration for a some module.
        The controller responds with a :py:class:`GetConfigResponse`.

        .. uml::

           Client -> Controller: **GetConfigRequest**()
           activate Controller
           note over Controller: gets module config
           Controller -> Client: GetConfigResponse()
           deactivate Controller
    """
    module: Path
    """path id of the module that will be examined"""


class GetConfigResponse(Response):
    """A response to :py:class:`GetConfigRequest` conveying the element configuration of some module

    .. uml::

           Client -> Controller: GetConfigRequest()
           activate Controller
           note over Controller: gets module config
           Controller -> Client: **GetConfigResponse**()
           deactivate Controller
    """
    response_for = GetConfigRequest
    __root__: GetConfigDict

    def to_module_config(self, module: Module):
        """Parses this message to a :py:class:`ModuleSchema`, that can be used to configurate a :py:class:`Module`"""
        ...


class SetDAQRequest(Request):
    """A request to the controller to set a :py:class:`DAQConfiguration` determining how and when data should be
    acquired. The controller will respond with a :py:class:`SetDAQResponse`

    .. uml::

           Client -> Controller: **SetDAQRequest**()
           Controller -> Client: SetDAQResponse()
    """
    #: Paths of elements that should be sampled
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

           Client -> Controller: SetDAQRequest()
           Controller -> Client: **SetDAQResponse**()
    """
    response_for = SetDAQRequest
    __root__: typing.Union[
        SuccessInfo, typing.List[typing.Union[SuccessInfo, typing.Dict]]
    ]


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
    #: A :py:class:`pyanabrid.modelone.run.RunConfig` that should be applied to the run.
    config: RunConfig

    @classmethod
    def from_run(cls, run):
        """
        Generate a :py:class:`pyanabrid.modelone.protocol.messages.StartRunRequest`
        from a :py:class:`pyanabrid.modelone.run.Run` instance.

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

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

import typing
from collections import defaultdict
from enum import Enum, auto
from pydantic import BaseModel, Field

from pyanabrid.hybrid.protocol.v1.types import RunState as ProtocolRunState


class RunState(Enum):
    ERROR = auto()
    NEW = auto()
    QUEUED = auto()
    TAKE_OFF = auto()
    IC = auto()
    OP = auto()
    OP_END = auto()
    DONE = auto()

    @classmethod
    def from_v1_protocol(cls, v1_run_state):
        # TODO: All (machine_type, protocol_version) conversion should be abstracted
        return {
            ProtocolRunState.ERROR: RunState.ERROR,
            ProtocolRunState.QUEUED: RunState.QUEUED,
            ProtocolRunState.TAKE_OFF: RunState.TAKE_OFF,
            ProtocolRunState.IC: RunState.IC,
            ProtocolRunState.OP: RunState.OP,
            ProtocolRunState.OP_END: RunState.OP_END,
            ProtocolRunState.DONE: RunState.DONE,
        }[v1_run_state]


class BaseRun(BaseModel):
    run_id: typing.Any
    state: RunState = RunState.NEW

    ctrl_period: int = 1_000
    ic_time: int = 50_000
    op_time: int = 100_000

    data: typing.Dict[RunState, typing.List[typing.Any]] = Field(default_factory=lambda: defaultdict(lambda: list()))

    def __str__(self):
        return f"Run {self.run_id} @{self.state}"

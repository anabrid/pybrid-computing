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
from dataclasses import dataclass
from enum import Enum
from uuid import UUID

from pyanabrid.base.hybrid import BaseRun, BaseRunConfig, BaseRunFlags, BaseRunState


@dataclass(kw_only=True)
class RunConfig(BaseRunConfig):
    ic_time: int = 50_000
    op_time: int = 100_000

    halt_on_external_trigger: bool = False
    halt_on_overload: bool = False


@dataclass(kw_only=True)
class RunFlags(BaseRunFlags):
    externally_halted: bool = False
    overloaded: bool = False


class RunState(BaseRunState, Enum):
    NEW = "NEW"
    ERROR = "ERROR"
    DONE = "DONE"
    QUEUED = "QUEUED"
    TAKE_OFF = "TAKE_OFF"
    IC = "IC"
    OP = "OP"
    TMP_HALT = "TMP_HALT"
    OP_END = "OP_END"

    @classmethod
    def default(cls):
        return cls.NEW

    @classmethod
    def get_possibly_sampled_states(cls):
        return cls.IC, cls.OP, cls.OP_END

    def is_done(self):
        return self in (RunState.DONE, RunState.ERROR)


@dataclass(kw_only=True)
class DAQConfiguration:
    pass


@dataclass(kw_only=True)
class Run(BaseRun):
    id_: UUID
    config: RunConfig

    state: RunState
    flags: RunFlags

    daq: DAQConfiguration
    data: typing.Any

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
from dataclasses import dataclass, field
from datetime import datetime


# Can't use an enum if we want to split states into base states and more advanced states
# TODO: Make functions abstract, but requires metaclass combination with enum
class BaseRunState:
    @classmethod
    def default(cls):
        raise NotImplementedError

    def is_done(self):
        raise NotImplementedError


class BaseRunConfig:
    pass


class BaseRunFlags:
    pass


class BaseDAQConfig:
    pass


@dataclass(kw_only=True)
class BaseRun:
    id_: typing.Any
    created: datetime = field(default_factory=lambda: datetime.now())
    config: BaseRunConfig = field(default_factory=lambda: BaseRunConfig())

    state: BaseRunState = field(default_factory=lambda: BaseRunState.default())
    flags: BaseRunFlags = field(default_factory=lambda: BaseRunFlags())

    daq: BaseDAQConfig = field(default_factory=BaseDAQConfig)
    data: typing.Optional[typing.Any] = None

    def __str__(self):
        return f"Run {self.id_} @{self.state}"

    @classmethod
    def get_persistent_attributes(cls) -> set[str]:
        """
        Get a list of attributes that should usually be persistent between consecutive runs.
        For example, it's reasonable to persist the 'config' attribute in a series of runs.
        :return: List of attribute names to persist
        """
        return {"config"}

    @classmethod
    def make_from_other_run(cls, other: typing.Optional["BaseRun"], **overwrites) -> "BaseRun":
        if other is not None:
            kwargs = {attr_: getattr(other, attr_) for attr_ in cls.get_persistent_attributes()}
            kwargs.update(overwrites)
        else:
            kwargs = overwrites
        return cls(**kwargs)

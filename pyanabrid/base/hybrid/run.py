# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

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

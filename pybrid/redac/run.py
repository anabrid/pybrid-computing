# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import typing
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from uuid import UUID, uuid4

from pybrid.base.hybrid import BaseRun, BaseRunConfig, BaseRunFlags, BaseRunState, BaseDAQConfig
from pybrid.base.utils.descriptors import Validator

from .entities import Path


class RunError(Exception):
    """Base exception class for all errors during a :class:`Run`."""
    pass


@dataclass(kw_only=True)
class RunConfig(BaseRunConfig):
    """Configures parameters related to the execution of one :class:`Run`."""
    #: Duration of IC (initial condition) mode in nanoseconds.
    ic_time: int = 100_000
    #: Duration of OP (operating) mode in nanoseconds.
    op_time: int = 2_000_000

    #: Whether to halt the computation when the external halt signal is triggered.
    halt_on_external_trigger: bool = False
    #: Whether to halt the computation when it enters an overload.
    halt_on_overload: bool = True


@dataclass(kw_only=True)
class RunFlags(BaseRunFlags):
    """
    Flags that can be triggered by a :class:`Run`.
    Once triggered, they are persistently `True`, even when the original condition is lost.
    """
    #: Whether the run was halted because of an external halt trigger.
    externally_halted: bool = False
    #: Any element that entered an overload during computation.
    overloaded: typing.Optional[list[Path]] = None


class RunState(BaseRunState, Enum):
    """The state of a :class:`Run`."""
    #: Run has just been created.
    NEW = "NEW"
    #: Run has encountered an error and has been aborted.
    ERROR = "ERROR"
    #: Run has successfully finished.
    DONE = "DONE"
    #: Run is queued for execution.
    QUEUED = "QUEUED"
    #: Run has been selected for execution and is being prepared to start.
    TAKE_OFF = "TAKE_OFF"
    #: Run is in IC (initial condition) mode.
    IC = "IC"
    #: Run is in OP (operating) mode.
    OP = "OP"
    #: Run is principally done, pending final data acquisition or other finalizing tasks.
    OP_END = "OP_END"
    #: Run is temporarily halted and can be resumed.
    TMP_HALT = "TMP_HALT"

    @classmethod
    def default(cls):
        return cls.NEW

    @classmethod
    def get_possibly_sampled_states(cls):
        """Return a list of states in which data acquisition is possible."""
        return cls.IC, cls.OP, cls.OP_END

    def is_done(self):
        return self in (RunState.DONE, RunState.ERROR)


class DAQConfigurationNumChannels(Validator):

    def set_default(self, instance, name, owner):
        setattr(instance, name, 0)

    def parse(self, instance, value):
        return int(value)

    def validate(self, instance, value):
        if value > 0 and (value & (value - 1)) != 0:
            raise ValueError("Value must be a power-of-two.")


@dataclass(kw_only=True)
class DAQConfig(BaseDAQConfig):
    #: List of channels that should be sampled.
    #: The element corresponding to each channel is implicitly defined by the computer's configuration.
    num_channels: int = field(default=DAQConfigurationNumChannels())
    #: Sample rate to use in samples/second.
    sample_rate: int = 500_000
    #: Whether to sample during IC
    sample_op: bool = True
    #: Whether to sample during OP_END
    sample_op_end: bool = True


@dataclass(kw_only=True)
class Run(BaseRun):
    """A run is one computation executed by the REDAC."""
    #: A unique identifier for the run.
    id_: UUID = field(default_factory=uuid4)
    #: Possibly the ID of a related run, e.g. one that triggered this one.
    related_to: typing.Optional[UUID] = None
    #: Defines the duration the run should be executed and similar parameters.
    #: Does not contain element configuration.
    config: RunConfig = field(default_factory=RunConfig)

    #: The current state of the run.
    state: RunState = RunState.NEW
    #: Flags, e.g. overload, the run has triggered. These are persistent once triggered.
    flags: RunFlags = field(default_factory=RunFlags)

    #: The configuration of the data acquisition for this run.
    daq: DAQConfig = field(default_factory=DAQConfig)
    #: Data captured for this run.
    data: dict[Path | str, list[float]] = field(default_factory=lambda: defaultdict(list))

    @classmethod
    def get_persistent_attributes(cls) -> set[str]:
        return super().get_persistent_attributes().union({"daq"})

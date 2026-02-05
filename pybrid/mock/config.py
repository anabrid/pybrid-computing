# Copyright (c) 2022-2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""Configuration classes for the DummyDAC mock server."""

import typing
from dataclasses import dataclass
from enum import Enum


class DummyDACErrorStage(Enum):
    """
    Defines at which stage the DummyDAC should inject an error.

    This allows testing error handling at various points in the
    communication and run lifecycle.
    """
    #: No error injection.
    NONE = "NONE"
    #: Error during configuration phase.
    AT_CONFIGURE = "AT_CONFIGURE"
    #: Error when starting a run.
    AT_START_RUN = "AT_START_RUN"
    #: Error during data extraction.
    AT_EXTRACT = "AT_EXTRACT"
    #: Error during run execution.
    DURING_RUN = "DURING_RUN"
    #: Drop the takeoff state message (simulates communication failure).
    DROP_TAKEOFF_STATE = "DROP_TAKEOFF_STATE"
    #: Drop the done state message (simulates communication failure).
    DROP_DONE_STATE = "DROP_DONE_STATE"
    #: Return fewer samples than expected.
    FEWER_SAMPLES = "FEWER_SAMPLES"


class DummyDACMacMode(Enum):
    """
    Defines how the DummyDAC generates its MAC address.

    This affects how the mock device identifies itself on the network.
    """
    #: Use a virtual/generated MAC address.
    VIRTUAL = "VIRTUAL"
    #: Use a physical/real MAC address format.
    PHYSICAL = "PHYSICAL"


@dataclass(kw_only=True)
class DummyDACConfig:
    """
    Configuration for a DummyDAC mock server instance.

    This configuration controls the behavior of the mock DAC,
    including how it responds to requests and whether to inject errors.
    """
    #: Mode for MAC address generation.
    mac_mode: DummyDACMacMode = DummyDACMacMode.VIRTUAL
    #: Whether to accept UDP streaming requests.
    accept_udp_streaming: bool = True
    #: Stage at which to inject an error (if any).
    error_stage: DummyDACErrorStage = DummyDACErrorStage.NONE
    #: Custom error message to return when error is injected.
    error_message: typing.Optional[str] = None

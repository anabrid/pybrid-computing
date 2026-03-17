# Copyright (c) 2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from pybrid.base.result import Result

if TYPE_CHECKING:
    from pybrid.base.hybrid.computer import AnalogComputer


class ConfigValidator(ABC):
    """Validates an AnalogComputer configuration before serialization."""

    @abstractmethod
    def validate(self, computer: "AnalogComputer") -> Result:
        """Return a :class:`Result` — ``ok=True`` on success, ``ok=False``
        with an error description on failure."""
        ...


__all__ = ["ConfigValidator"]

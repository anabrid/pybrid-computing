# Copyright (c) 2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""Result type for control-channel command outcomes."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Result:
    """Outcome of a control-channel command.

    Attributes:
        ok:    True if the command succeeded.
        error: Human-readable error description, or empty string on success.
    """

    ok: bool
    error: str = ""

    @staticmethod
    def success() -> "Result":
        return Result(ok=True)

    @staticmethod
    def failure(error: str) -> "Result":
        return Result(ok=False, error=error)

    def raise_on_error(self) -> None:
        """:raises RuntimeError: If this result represents a failure."""
        if not self.ok:
            raise RuntimeError(f"Device returned error: {self.error}")

# Copyright (c) 2022-2025 anabrid GmbH
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
Expansion and parsing for the proxy CLI command.

Each ``-b`` value passed to ``pybrid proxy`` can be:

* A single ``HOST[:PORT][/STACK/CARRIER]`` string.
* A comma-separated list of strings.
* A path to a file containing one string per line
  (blank lines and ``#``-comments are ignored).
"""

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class BackendSpec:
    """Parsed backend endpoint with optional carrier location."""

    host: str
    port: int = 5732
    stack: Optional[int] = None
    carrier: Optional[int] = None


def parse_backend_spec(raw: str) -> BackendSpec:
    """Parse a raw backend string in ``HOST[:PORT][/STACK/CARRIER]`` format.

    Args:
        raw: A string like ``"192.168.1.10"``, ``"192.168.1.10:5733"``,
             ``"192.168.1.10/0/2"``, or ``"192.168.1.10:5733/0/2"``.

    Returns:
        A :class:`BackendSpec` with host, port, and optional stack/carrier.

    Raises:
        ValueError: If a location separator ``/`` is present but only one
            index (stack without carrier) is supplied.
    """
    stack: Optional[int] = None
    carrier: Optional[int] = None

    host_port_part, _, location_part = raw.partition("/")

    if location_part:
        parts = location_part.split("/")
        if len(parts) != 2:
            raise ValueError(
                f"Invalid backend spec {raw!r}: location must be STACK/CARRIER, got {location_part!r}"
            )
        stack = int(parts[0])
        carrier = int(parts[1])

    if ":" in host_port_part:
        host, port_str = host_port_part.rsplit(":", 1)
        port = int(port_str)
    else:
        host = host_port_part
        port = 5732

    return BackendSpec(host=host, port=port, stack=stack, carrier=carrier)


def expand_args(specs: tuple[str, ...]) -> list[str]:
    """Expand a tuple of raw ``-b`` / ``-a`` values into a flat list of entries,
    reading from a file if necessary.

    Args:
        specs: Raw values from the ``-a`` / ``-b`` CLI options.

    Returns:
        A flat list of ``HOST[:PORT]`` / ``STACK/CARRIER`` strings ready for further parsing.

    Raises:
        FileNotFoundError: If a spec looks like a file path but the file
            does not exist.
    """
    result: list[str] = []
    for spec in specs:
        if os.path.isfile(spec):
            with open(spec) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        result.append(line)
        else:
            for part in spec.split(","):
                part = part.strip()
                if part:
                    result.append(part)
    return result
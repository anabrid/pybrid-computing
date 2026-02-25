# Copyright (c) 2022-2025 anabrid GmbH
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
Backend spec expansion for the proxy CLI command.

Each ``-b`` value passed to ``pybrid proxy`` can be:

* A single ``HOST[:PORT]`` string.
* A comma-separated list of ``HOST[:PORT]`` strings.
* A path to a file containing one ``HOST[:PORT]`` per line
  (blank lines and ``#``-comments are ignored).
"""

import os


def expand_backend_specs(specs: tuple[str, ...]) -> list[str]:
    """Expand a tuple of raw ``-b`` values into a flat list of backend specs.

    Args:
        specs: Raw values from the ``--backend`` / ``-b`` CLI option.

    Returns:
        A flat list of ``HOST[:PORT]`` strings ready for further parsing.

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

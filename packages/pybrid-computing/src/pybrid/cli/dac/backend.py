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
import os.path
from dataclasses import dataclass
from typing import Optional, Union

from lark import Lark, Visitor

from pybrid.base.hybrid.computer import NamedPin, validate_named_pin


@dataclass
class CarrierSpec:
    """Parsed backend endpoint with optional carrier location."""

    host: str
    port: int = 5732
    stack: Optional[int] = None
    carrier: Optional[int] = None


@dataclass
class WireSpec:
    """Parsed wiring between two backends."""

    source_carrier: int
    source_pin: Union[NamedPin, int]

    target_carrier: int
    target_pin: Union[NamedPin, int]

    source_stack: Optional[int] = None
    target_stack: Optional[int] = None

    def __post_init__(self) -> None:
        validate_named_pin(self.source_pin)
        validate_named_pin(self.target_pin)


class BackendStringParser:
    """
    This parser parses backend files containing carriers and wires. These files
    define which devices the proxy should manage. Addiitonal information, such as location
    and wires, is injected in the device' spec.

    This version also accepts a legacy format of <IP>/<stack>/<carrier> as well
    as comma-seperated strings.
    """

    LARK_DEFINITION = r"""
NEWLINE: /\r?\n/
LABEL: /[a-zA-Z]([a-zA-Z0-9-]*[a-zA-Z0-9])?/
INTEGER: /[0-9]+/
COMMENT: /#[^\r\n]*/

ip: INTEGER ~ 1..3 "." INTEGER ~ 1..3 "." INTEGER ~ 1..3 "." INTEGER ~ 1..3
hostname: LABEL ("." LABEL)*
host: (hostname | ip) (":" INTEGER)?

carrier_loc: (INTEGER "/")? INTEGER
wire_pin: INTEGER | LABEL
wire_loc: carrier_loc "/" wire_pin
carrier_def: "carrier" " " host (" " carrier_loc)?
legacy_carrier_def: host ("/" carrier_loc)?
wire_def: "wire" " " wire_loc " " wire_loc
def: carrier_def | legacy_carrier_def | wire_def

start: line+
line: def NEWLINE | NEWLINE

%ignore COMMENT
    """

    class BackendStringParserDefHandler(Visitor):
        def __init__(self, source: str):
            self.carriers: list[CarrierSpec] = []
            self.wires: list[WireSpec] = []

            self.source = source

        def find_token_range(self, node):
            """Return (start, end) char offsets covering all tokens under node."""
            if hasattr(node, "children"):
                starts, ends = [], []
                for c in node.children:
                    r = self.find_token_range(c)
                    if r is not None:
                        starts.append(r[0])
                        ends.append(r[1])
                if not starts:
                    return None
                return min(starts), max(ends)
            # it's a Token
            return node.start_pos, node.end_pos

        def node_to_str(self, node):
            r = self.find_token_range(node)
            if r is None:
                return ""
            return self.source[r[0] : r[1]]

        def parse_carrier_loc(self, tree) -> list[int | None]:

            if len(tree.children) == 1:
                return [None, int(tree.children[0].value)]

            return [int(tree.children[0].value), int(tree.children[1].value)]

        def parse_wire_loc(self, tree) -> list:
            """Parse a wire_loc into [stack, carrier, pin].

            Stack and carrier come from the nested carrier_loc; pin is the
            wire_pin child which may be either INTEGER or LABEL. Validity of
            string pins is enforced by ``WireSpec.__post_init__``.
            """
            carrier_parts = self.parse_carrier_loc(tree.children[0])
            pin_token = tree.children[1].children[0]
            pin = str(pin_token) if pin_token.type == "LABEL" else int(pin_token)
            return [*carrier_parts, pin]

        def parse_host(self, tree) -> tuple[str, int]:
            return (
                self.node_to_str(tree.children[0]),
                int(tree.children[1].value) if len(tree.children) == 2 else 5732,
            )

        # visitor rules, auto-used by LARK
        def wire_def(self, tree):
            source_loc = self.parse_wire_loc(tree.children[0])
            target_loc = self.parse_wire_loc(tree.children[1])

            self.wires.append(
                WireSpec(
                    source_stack=source_loc[0],
                    source_carrier=source_loc[1],
                    source_pin=source_loc[2],
                    target_stack=target_loc[0],
                    target_carrier=target_loc[1],
                    target_pin=target_loc[2],
                )
            )

        def legacy_carrier_def(self, tree):
            self.carrier_def(tree)

        def carrier_def(self, tree):
            host = self.parse_host(tree.children[0])
            if len(tree.children) >= 2:
                loc = self.parse_carrier_loc(tree.children[1])
            else:
                loc = [None, None]

            self.carriers.append(CarrierSpec(host=host[0], port=host[1], stack=loc[0], carrier=loc[1]))

    @staticmethod
    def parse(input: str) -> tuple[list[CarrierSpec], list[WireSpec]]:

        # input is file: read file; input is string: split along commata to turn
        # into definition file
        input_data: str = input
        if os.path.exists(input_data):
            with open(input_data, "r") as f:
                input_data = f.read()
        else:
            input_data = input_data.replace(",", "\n") + "\n"

        # parse file by LARK, then create Pythonic objects
        parser = Lark(BackendStringParser.LARK_DEFINITION)
        parsed = parser.parse(input_data)

        visitor = BackendStringParser.BackendStringParserDefHandler(input_data)
        visitor.visit(parsed)

        return (visitor.carriers, visitor.wires)

# Copyright (c) 2022-2025 anabrid GmbH
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
Unit tests for the proxy backend string parser (carriers + wires).
"""

from pathlib import Path

import pytest
from lark.exceptions import UnexpectedCharacters, UnexpectedInput

from pybrid.cli.dac.backend import BackendStringParser, CarrierSpec, WireSpec

EXAMPLE_FILE = Path(__file__).parents[2] / "examples" / "proxy" / "list-lucistack-bernd.txt"


class TestExampleFile:

    def test_parse_example_file(self):
        carriers, wires = BackendStringParser.parse(str(EXAMPLE_FILE))

        assert carriers == [
            CarrierSpec(host="192.168.150.57", port=5732, stack=None, carrier=0),
            CarrierSpec(host="192.168.150.17", port=5732, stack=None, carrier=1),
        ]

        assert len(wires) == 8
        assert wires[0] == WireSpec(
            source_stack=None, source_carrier=0, source_pin=4,
            target_stack=None, target_carrier=1, target_pin=4,
        )
        assert wires[-1] == WireSpec(
            source_stack=None, source_carrier=1, source_pin=7,
            target_stack=None, target_carrier=0, target_pin=7,
        )

    def test_comments_and_blank_lines_ignored(self, tmp_path):
        f = tmp_path / "with-comments.txt"
        f.write_text(
            "# first carrier\n"
            "carrier 10.0.0.1 0\n"
            "\n"
            "# second carrier\n"
            "carrier 10.0.0.2 1\n"
        )

        carriers, wires = BackendStringParser.parse(str(f))
        assert len(carriers) == 2
        assert wires == []


class TestNewCarrierSyntax:

    def test_carrier_no_location(self):
        carriers, _ = BackendStringParser.parse("carrier 192.168.1.10")
        assert carriers == [CarrierSpec(host="192.168.1.10", port=5732, stack=None, carrier=None)]

    def test_carrier_with_carrier_index_only(self):
        carriers, _ = BackendStringParser.parse("carrier 192.168.1.10 3")
        assert carriers == [CarrierSpec(host="192.168.1.10", port=5732, stack=None, carrier=3)]

    def test_carrier_with_stack_and_carrier(self):
        carriers, _ = BackendStringParser.parse("carrier 192.168.1.10 2/3")
        assert carriers == [CarrierSpec(host="192.168.1.10", port=5732, stack=2, carrier=3)]

    def test_carrier_with_port(self):
        carriers, _ = BackendStringParser.parse("carrier 192.168.1.10:5733 0/1")
        assert carriers == [CarrierSpec(host="192.168.1.10", port=5733, stack=0, carrier=1)]

    def test_carrier_with_hostname(self):
        carriers, _ = BackendStringParser.parse("carrier lucidac-AA-BB-CC")
        assert carriers == [CarrierSpec(host="lucidac-AA-BB-CC", port=5732, stack=None, carrier=None)]


class TestLegacyStringInput:

    def test_legacy_bare_ip(self):
        carriers, wires = BackendStringParser.parse("192.168.150.57")
        assert carriers == [CarrierSpec(host="192.168.150.57", port=5732, stack=None, carrier=None)]
        assert wires == []

    def test_legacy_bare_hostname(self):
        carriers, _ = BackendStringParser.parse("lucidac-AA-BB-CC")
        assert carriers == [CarrierSpec(host="lucidac-AA-BB-CC", port=5732, stack=None, carrier=None)]

    def test_legacy_ip_with_port(self):
        carriers, _ = BackendStringParser.parse("192.168.150.57:5733")
        assert carriers == [CarrierSpec(host="192.168.150.57", port=5733, stack=None, carrier=None)]

    def test_legacy_ip_with_stack_carrier(self):
        carriers, _ = BackendStringParser.parse("192.168.150.57/0/2")
        assert carriers == [CarrierSpec(host="192.168.150.57", port=5732, stack=0, carrier=2)]

    def test_legacy_full(self):
        carriers, _ = BackendStringParser.parse("192.168.150.57:5733/0/2")
        assert carriers == [CarrierSpec(host="192.168.150.57", port=5733, stack=0, carrier=2)]

    def test_legacy_comma_separated(self):
        carriers, _ = BackendStringParser.parse("192.168.150.57,192.168.150.58")
        assert carriers == [
            CarrierSpec(host="192.168.150.57", port=5732, stack=None, carrier=None),
            CarrierSpec(host="192.168.150.58", port=5732, stack=None, carrier=None),
        ]

    def test_legacy_comma_separated_full(self):
        carriers, _ = BackendStringParser.parse(
            "192.168.150.57:5732/0/0,192.168.150.58:5733/1/3"
        )
        assert carriers == [
            CarrierSpec(host="192.168.150.57", port=5732, stack=0, carrier=0),
            CarrierSpec(host="192.168.150.58", port=5733, stack=1, carrier=3),
        ]


class TestLegacyFileInput:

    def test_legacy_one_ip_per_line(self, tmp_path):
        f = tmp_path / "backends.txt"
        f.write_text("192.168.1.1\n192.168.1.2\n192.168.1.3\n")

        carriers, wires = BackendStringParser.parse(str(f))
        assert [c.host for c in carriers] == ["192.168.1.1", "192.168.1.2", "192.168.1.3"]
        assert all(c.port == 5732 for c in carriers)
        assert wires == []

    def test_legacy_with_ports_comments_blanks(self, tmp_path):
        f = tmp_path / "backends.txt"
        f.write_text(
            "# Primary backends\n"
            "192.168.1.1:5733\n"
            "\n"
            "# Secondary backend\n"
            "192.168.1.2:5734\n"
            "\n"
        )

        carriers, _ = BackendStringParser.parse(str(f))
        assert carriers == [
            CarrierSpec(host="192.168.1.1", port=5733, stack=None, carrier=None),
            CarrierSpec(host="192.168.1.2", port=5734, stack=None, carrier=None),
        ]

    def test_legacy_mixed_with_locations(self, tmp_path):
        f = tmp_path / "backends.txt"
        f.write_text("192.168.1.1/0/0\n192.168.1.2/0/1\n")

        carriers, _ = BackendStringParser.parse(str(f))
        assert carriers == [
            CarrierSpec(host="192.168.1.1", port=5732, stack=0, carrier=0),
            CarrierSpec(host="192.168.1.2", port=5732, stack=0, carrier=1),
        ]


class TestWireSyntax:

    def test_wire_carrier_only_locations(self):
        _, wires = BackendStringParser.parse(
            "carrier 10.0.0.1 0\ncarrier 10.0.0.2 1\nwire 0/4 1/5\n"
        )
        assert wires == [
            WireSpec(
                source_stack=None, source_carrier=0, source_pin=4,
                target_stack=None, target_carrier=1, target_pin=5,
            )
        ]

    def test_wire_with_stack(self):
        _, wires = BackendStringParser.parse(
            "carrier 10.0.0.1 0/0\ncarrier 10.0.0.2 1/0\nwire 0/0/4 1/0/5\n"
        )
        assert wires == [
            WireSpec(
                source_stack=0, source_carrier=0, source_pin=4,
                target_stack=1, target_carrier=0, target_pin=5,
            )
        ]


class TestNamedPinSyntax:

    def test_named_pin_source_integer_target(self):
        _, wires = BackendStringParser.parse("wire 0/aux0 0/4\n")
        assert wires == [
            WireSpec(
                source_stack=None, source_carrier=0, source_pin="aux0",
                target_stack=None, target_carrier=0, target_pin=4,
            )
        ]

    def test_all_named_pins_accepted(self):
        for pin in ("aux0", "aux1", "gen0", "gen1"):
            _, wires = BackendStringParser.parse(f"wire 0/{pin} 0/4\n")
            assert wires[0].source_pin == pin

    def test_invalid_named_pin_raises_value_error(self):
        with pytest.raises(ValueError):
            BackendStringParser.parse("wire 0/foo 0/4\n")


class TestInvalidInputs:

    def test_invalid_garbage(self):
        with pytest.raises(UnexpectedInput):
            BackendStringParser.parse("$$$garbage###")

    def test_wire_missing_pin(self):
        with pytest.raises(UnexpectedInput):
            BackendStringParser.parse("wire 0/4\n")

    def test_wire_missing_separator(self):
        with pytest.raises(UnexpectedInput):
            BackendStringParser.parse("wire 0 1\n")

    def test_wire_with_extra_tokens(self):
        with pytest.raises(UnexpectedInput):
            BackendStringParser.parse("wire 0/4/3 1/4/2 extra\n")

    def test_too_many_location_parts(self):
        with pytest.raises(UnexpectedInput):
            BackendStringParser.parse("192.168.1.10/0/1/2\n")

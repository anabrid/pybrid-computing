# Copyright (c) 2022-2025 anabrid GmbH
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
Unit tests for backend spec expansion and parsing (proxy CLI command).
"""

import os

import pytest

from pybrid.cli.dac.backend import BackendSpec, expand_args, parse_backend_spec


class TestExpandCommaSeparated:

    def test_comma_separated_ips(self):
        result = expand_args(("192.168.1.1,192.168.1.2,192.168.1.3",))
        assert result == ["192.168.1.1", "192.168.1.2", "192.168.1.3"]

    def test_comma_separated_ips_with_ports(self):
        result = expand_args(("192.168.1.1:5733,192.168.1.2:5734",))
        assert result == ["192.168.1.1:5733", "192.168.1.2:5734"]

    def test_comma_separated_whitespace_trimmed(self):
        result = expand_args(("192.168.1.1 , 192.168.1.2",))
        assert result == ["192.168.1.1", "192.168.1.2"]

    def test_empty_entries_ignored(self):
        """Trailing commas and double commas produce empty strings that are skipped."""
        result = expand_args(("192.168.1.1,,192.168.1.2,",))
        assert result == ["192.168.1.1", "192.168.1.2"]


class TestExpandFromFile:

    def test_file_one_ip_per_line(self, tmp_path):
        f = tmp_path / "backends.txt"
        f.write_text("192.168.1.1\n192.168.1.2\n192.168.1.3\n")

        result = expand_args((str(f),))
        assert result == ["192.168.1.1", "192.168.1.2", "192.168.1.3"]

    def test_file_with_ports_comments_blanks(self, tmp_path):
        f = tmp_path / "backends.txt"
        f.write_text("# Primary backends\n" "192.168.1.1:5733\n" "\n" "# Secondary backend\n" "192.168.1.2:5734\n" "\n")

        result = expand_args((str(f),))
        assert result == ["192.168.1.1:5733", "192.168.1.2:5734"]


class TestExpandMixed:

    def test_mixed_single_comma_file(self, tmp_path):
        f = tmp_path / "backends.txt"
        f.write_text("10.0.0.3\n10.0.0.4\n")

        result = expand_args(
            (
                "10.0.0.1",
                "10.0.0.2:5733,10.0.0.5",
                str(f),
            )
        )
        assert result == [
            "10.0.0.1",
            "10.0.0.2:5733",
            "10.0.0.5",
            "10.0.0.3",
            "10.0.0.4",
        ]


class TestParseBackendSpec:

    def test_host_only(self):
        spec = parse_backend_spec("192.168.1.10")
        assert spec == BackendSpec(host="192.168.1.10", port=5732, stack=None, carrier=None)

    def test_host_with_port(self):
        spec = parse_backend_spec("192.168.1.10:5733")
        assert spec == BackendSpec(host="192.168.1.10", port=5733, stack=None, carrier=None)

    def test_host_with_location(self):
        spec = parse_backend_spec("192.168.1.10/0/2")
        assert spec == BackendSpec(host="192.168.1.10", port=5732, stack=0, carrier=2)

    def test_host_port_and_location(self):
        spec = parse_backend_spec("192.168.1.10:5733/0/2")
        assert spec == BackendSpec(host="192.168.1.10", port=5733, stack=0, carrier=2)

    def test_incomplete_location_raises(self):
        with pytest.raises(ValueError):
            parse_backend_spec("192.168.1.10/0")

    def test_too_many_location_parts_raises(self):
        with pytest.raises(ValueError):
            parse_backend_spec("192.168.1.10/0/1/2")

    def test_expand_then_parse_roundtrip(self):
        raw = "192.168.1.1:5732/0/0,192.168.1.2:5733/1/3"
        entries = expand_args((raw,))
        assert entries == ["192.168.1.1:5732/0/0", "192.168.1.2:5733/1/3"]

        specs = [parse_backend_spec(e) for e in entries]
        assert specs[0] == BackendSpec(host="192.168.1.1", port=5732, stack=0, carrier=0)
        assert specs[1] == BackendSpec(host="192.168.1.2", port=5733, stack=1, carrier=3)

# Copyright (c) 2022-2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
Unit tests for the Path class.

Tests cover:
- String parsing with various formats (leading/trailing slashes, empty paths)
- Path passthrough (parsing a Path returns same object)
- Alias expansion during parsing
- Error handling for invalid types
- Join operations with strings, Path instances, and tuples
- Division operator (/) as join shorthand
- Navigation methods (to_root, to_parent)
- Properties (parent, root, id_, depth)
- String conversion and roundtrip consistency
"""

import pytest

from pybrid.base.hybrid.entities import Path


class TestPathParse:
    """Test cases for Path.parse() string parsing and error handling."""

    @pytest.mark.parametrize(
        "path_str,expected_tuple",
        [
            # Basic path segments
            ("a", ("a",)),
            ("a/b", ("a", "b")),
            ("a/b/c", ("a", "b", "c")),
            # Leading slash should be stripped
            ("/a", ("a",)),
            ("/a/b", ("a", "b")),
            # Trailing slash should be stripped
            ("a/", ("a",)),
            ("a/b/", ("a", "b")),
            # Both leading and trailing slashes
            ("/a/b/", ("a", "b")),
            # Empty string becomes empty path
            ("", ()),
            ("/", ()),
            # Numeric-looking segments remain strings
            ("0/1/2", ("0", "1", "2")),
            # Mixed alphanumeric segments
            ("carrier0/cluster1/U", ("carrier0", "cluster1", "U")),
        ],
    )
    def test_parse_strings(self, path_str: str, expected_tuple: tuple):
        """Verify that various path strings are parsed into expected tuple form."""
        path = Path.parse(path_str)
        assert tuple(path) == expected_tuple
        assert isinstance(path, Path)

    def test_parse_path_passthrough(self):
        """Parsing a Path instance should return the same object (passthrough)."""
        original = Path.parse("a/b/c")
        parsed = Path.parse(original)
        assert parsed is original

    def test_parse_with_alias(self):
        """Path parsing should expand aliases at the start of the path."""
        aliases = {
            "root": Path.parse("device/carrier"),
            "cluster": Path.parse("cluster0"),
        }

        # Alias at start gets expanded
        result = Path.parse("root/0/U", aliases=aliases)
        assert tuple(result) == ("device", "carrier", "0", "U")

        # Different alias
        result = Path.parse("cluster/block", aliases=aliases)
        assert tuple(result) == ("cluster0", "block")

        # No alias match uses path as-is
        result = Path.parse("other/path", aliases=aliases)
        assert tuple(result) == ("other", "path")

    def test_parse_invalid_type_raises(self):
        """Parsing non-string, non-Path types should raise TypeError."""
        with pytest.raises(TypeError, match="Paths can be parsed only from strings"):
            Path.parse(12345)

        with pytest.raises(TypeError, match="Paths can be parsed only from strings"):
            Path.parse(["a", "b"])

        with pytest.raises(TypeError, match="Paths can be parsed only from strings"):
            Path.parse(None)


class TestPathOperations:
    """Test cases for Path join, navigation, and property access."""

    def test_join_string(self):
        """Joining a string appends it as a single segment."""
        base = Path.parse("a/b")
        result = base.join("c")
        assert tuple(result) == ("a", "b", "c")
        assert isinstance(result, Path)

    def test_join_path(self):
        """Joining another Path concatenates all its segments."""
        base = Path.parse("a/b")
        other = Path.parse("c/d")
        result = base.join(other)
        assert tuple(result) == ("a", "b", "c", "d")
        assert isinstance(result, Path)

    def test_join_tuple(self):
        """Joining a tuple appends each element as a segment."""
        base = Path.parse("a")
        result = base.join(("b", "c", "d"))
        assert tuple(result) == ("a", "b", "c", "d")
        assert isinstance(result, Path)

    def test_join_non_iterable(self):
        """Joining a non-iterable (like an int) wraps it in a tuple."""
        base = Path.parse("carrier")
        result = base.join(0)
        assert tuple(result) == ("carrier", 0)

    def test_division_operator(self):
        """The / operator should work as a shorthand for join."""
        base = Path.parse("a/b")

        # String join
        result = base / "c"
        assert tuple(result) == ("a", "b", "c")

        # Path join
        other = Path.parse("d/e")
        result = base / other
        assert tuple(result) == ("a", "b", "d", "e")

        # Chained operations
        result = Path.parse("root") / "level1" / "level2"
        assert tuple(result) == ("root", "level1", "level2")

    def test_to_root(self):
        """to_root() should return a Path containing only the first segment."""
        path = Path.parse("carrier/cluster/block")
        root_path = path.to_root()
        assert tuple(root_path) == ("carrier",)
        assert isinstance(root_path, Path)

    def test_to_parent(self):
        """to_parent() should return a Path without the last segment."""
        path = Path.parse("carrier/cluster/block")
        parent_path = path.to_parent()
        assert tuple(parent_path) == ("carrier", "cluster")
        assert isinstance(parent_path, Path)

    def test_parent_property(self):
        """The parent property should return the path without the last segment."""
        path = Path.parse("a/b/c")
        assert tuple(path.parent) == ("a", "b")

        # Single segment path has empty parent
        single = Path.parse("root")
        assert tuple(single.parent) == ()

    def test_root_property(self):
        """The root property should return the first segment of the path."""
        path = Path.parse("carrier/cluster/block")
        assert path.root == "carrier"

    def test_id_property(self):
        """The id_ property should return the last segment of the path."""
        path = Path.parse("carrier/cluster/block")
        assert path.id_ == "block"

        # Works with numeric-like segments too
        path = Path.parse("carrier/0")
        assert path.id_ == "0"

    def test_depth_property(self):
        """The depth property should return the number of segments."""
        assert Path.parse("").depth == 0
        assert Path.parse("a").depth == 1
        assert Path.parse("a/b").depth == 2
        assert Path.parse("a/b/c/d").depth == 4

    def test_str_conversion(self):
        """String conversion should produce slash-separated path."""
        path = Path.parse("carrier/cluster/block")
        assert str(path) == "carrier/cluster/block"

        # Empty path
        empty = Path.parse("")
        assert str(empty) == ""

        # Single segment
        single = Path.parse("root")
        assert str(single) == "root"

    def test_str_roundtrip(self):
        """Parsing the string representation should yield equivalent path."""
        original_strings = [
            "a/b/c",
            "carrier/0/U",
            "single",
            "",
        ]

        for original_str in original_strings:
            path = Path.parse(original_str)
            roundtrip = Path.parse(str(path))
            assert tuple(path) == tuple(roundtrip)
            assert str(path) == str(roundtrip)


class TestPathConstruction:
    """Test cases for Path construction methods."""

    def test_make_root(self):
        """make_root() should create a single-segment path."""
        path = Path.make_root("carrier")
        assert tuple(path) == ("carrier",)
        assert isinstance(path, Path)

    def test_make_multiple_parts(self):
        """make() should create a path from multiple parts."""
        path = Path.make("a", "b", "c")
        assert tuple(path) == ("a", "b", "c")
        assert isinstance(path, Path)

    def test_make_empty(self):
        """make() with no arguments should create an empty path."""
        path = Path.make()
        assert tuple(path) == ()
        assert path.depth == 0


class TestPathPydanticIntegration:
    """Test cases for Pydantic v2 integration."""

    def test_pydantic_validate_from_path(self):
        """Pydantic validator should pass through Path instances."""
        original = Path.parse("a/b")
        result = Path._pydantic_validate(original)
        assert result is original

    def test_pydantic_validate_from_list(self):
        """Pydantic validator should convert lists to Path."""
        result = Path._pydantic_validate(["a", "b", "c"])
        assert tuple(result) == ("a", "b", "c")
        assert isinstance(result, Path)

    def test_pydantic_validate_from_tuple(self):
        """Pydantic validator should convert tuples to Path."""
        result = Path._pydantic_validate(("x", "y"))
        assert tuple(result) == ("x", "y")
        assert isinstance(result, Path)

    def test_pydantic_validate_from_string(self):
        """Pydantic validator should parse strings via Path.parse()."""
        result = Path._pydantic_validate("carrier/cluster")
        assert tuple(result) == ("carrier", "cluster")
        assert isinstance(result, Path)

    def test_pydantic_validate_invalid_type(self):
        """Pydantic validator should raise ValueError for invalid types."""
        with pytest.raises(ValueError, match="Cannot convert"):
            Path._pydantic_validate(12345)

        with pytest.raises(ValueError, match="Cannot convert"):
            Path._pydantic_validate({"a": "b"})

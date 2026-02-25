# Copyright (c) 2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""Unit tests for pybrid.processing.gap_fill module.

Tests cover sort_and_fill_chunks() with all GapFillMode variants,
edge cases (empty input, single chunk), out-of-order detection,
multi-channel interpolation, and backward-compatibility imports.
"""

import numpy as np
import pytest

from pybrid.processing.gap_fill import (
    ChunkRecord,
    GapFillMode,
    sort_and_fill_chunks,
)


def _make_chunk(
    chunk_number: int,
    samples: np.ndarray,
    *,
    entity_path: str = "/MAC/Carrier0",
    sample_type: int = 0,
) -> ChunkRecord:
    """Helper to build a ChunkRecord from a samples array.

    :param chunk_number: Chunk sequence number.
    :param samples: 2-D array of shape ``(channel_count, sample_count)``.
    :param entity_path: Entity path string.
    :param sample_type: 0 = OP, 1 = OP_END.
    :returns: A frozen ChunkRecord.
    """
    assert samples.ndim == 2
    return ChunkRecord(
        chunk_number=chunk_number,
        entity_path=entity_path,
        sample_type=sample_type,
        channel_count=samples.shape[0],
        samples=samples,
    )


class TestSortAndFillChunks:

    def test_no_gap_passthrough(self):
        """Chunks [0,1,2] in order are returned as-is with no gap."""
        chunks = [
            _make_chunk(0, np.array([[1.0, 2.0]])),
            _make_chunk(1, np.array([[3.0, 4.0]])),
            _make_chunk(2, np.array([[5.0, 6.0]])),
        ]
        filled, gap, reordered = sort_and_fill_chunks(chunks, GapFillMode.ZERO)
        assert not gap
        assert not reordered
        assert len(filled) == 3
        assert [c.chunk_number for c in filled] == [0, 1, 2]
        np.testing.assert_array_equal(filled[0].samples, chunks[0].samples)

    def test_out_of_order_sorted(self):
        """Chunks [2,0,1] are sorted to [0,1,2] with reordered=True."""
        chunks = [
            _make_chunk(2, np.array([[5.0, 6.0]])),
            _make_chunk(0, np.array([[1.0, 2.0]])),
            _make_chunk(1, np.array([[3.0, 4.0]])),
        ]
        filled, gap, reordered = sort_and_fill_chunks(chunks, GapFillMode.ZERO)
        assert not gap
        assert reordered
        assert [c.chunk_number for c in filled] == [0, 1, 2]
        np.testing.assert_array_equal(filled[0].samples, np.array([[1.0, 2.0]]))
        np.testing.assert_array_equal(filled[2].samples, np.array([[5.0, 6.0]]))

    def test_single_gap_zero(self):
        """Chunks [0,2] with ZERO mode fills chunk 1 with zeros."""
        chunks = [
            _make_chunk(0, np.array([[1.0, 2.0]])),
            _make_chunk(2, np.array([[5.0, 6.0]])),
        ]
        filled, gap, reordered = sort_and_fill_chunks(chunks, GapFillMode.ZERO)
        assert gap
        assert not reordered
        assert len(filled) == 3
        assert filled[1].chunk_number == 1
        np.testing.assert_array_equal(filled[1].samples, np.array([[0.0, 0.0]]))

    def test_single_gap_repeat(self):
        """Chunks [0,2] with REPEAT mode fills chunk 1 with trailing values."""
        chunks = [
            _make_chunk(0, np.array([[1.0, 2.0]])),
            _make_chunk(2, np.array([[5.0, 6.0]])),
        ]
        filled, gap, reordered = sort_and_fill_chunks(chunks, GapFillMode.REPEAT)
        assert gap
        assert len(filled) == 3
        assert filled[1].chunk_number == 1
        # Trailing value of chunk 0 is 2.0 for channel 0.
        np.testing.assert_array_equal(filled[1].samples, np.array([[2.0, 2.0]]))

    def test_single_gap_interpolate(self):
        """Chunks [0,2] with INTERPOLATE: linear ramp from trailing to leading.

        Chunk 0 trailing = [2.0], chunk 2 leading = [5.0].
        Gap = 1 chunk × 2 samples = 2 positions, divisor = 3.
        Position 0: 2.0 + 3.0 * 1/3 = 3.0
        Position 1: 2.0 + 3.0 * 2/3 = 4.0
        """
        chunks = [
            _make_chunk(0, np.array([[1.0, 2.0]])),
            _make_chunk(2, np.array([[5.0, 6.0]])),
        ]
        filled, gap, reordered = sort_and_fill_chunks(
            chunks, GapFillMode.INTERPOLATE
        )
        assert gap
        assert len(filled) == 3
        assert filled[1].chunk_number == 1
        np.testing.assert_allclose(filled[1].samples, np.array([[3.0, 4.0]]))

    def test_multi_gap_interpolate(self):
        """Chunks [0,4] with INTERPOLATE fills 3 chunks (1,2,3).

        Chunk 0 trailing = [10.0], chunk 4 leading = [50.0].
        Gap = 3 chunks × 2 samples = 6 positions, divisor = 7.
        Position k: 10.0 + 40.0 * (k+1)/7.
        """
        chunks = [
            _make_chunk(0, np.array([[0.0, 10.0]])),
            _make_chunk(4, np.array([[50.0, 60.0]])),
        ]
        filled, gap, _ = sort_and_fill_chunks(chunks, GapFillMode.INTERPOLATE)
        assert gap
        assert len(filled) == 5
        assert [c.chunk_number for c in filled] == [0, 1, 2, 3, 4]

        # Verify ramp values: trailing=10.0, leading=50.0, delta=40.0, G=6
        expected_positions = []
        for p in range(6):
            expected_positions.append(10.0 + 40.0 * (p + 1) / 7)

        # Chunk 1 gets positions 0,1; chunk 2 gets 2,3; chunk 3 gets 4,5.
        np.testing.assert_allclose(
            filled[1].samples[0],
            [expected_positions[0], expected_positions[1]],
        )
        np.testing.assert_allclose(
            filled[2].samples[0],
            [expected_positions[2], expected_positions[3]],
        )
        np.testing.assert_allclose(
            filled[3].samples[0],
            [expected_positions[4], expected_positions[5]],
        )

    def test_none_mode_raises(self):
        """Chunks [0,2] with NONE mode raises RuntimeError."""
        chunks = [
            _make_chunk(0, np.array([[1.0, 2.0]])),
            _make_chunk(2, np.array([[5.0, 6.0]])),
        ]
        with pytest.raises(RuntimeError, match="Chunk gap detected"):
            sort_and_fill_chunks(chunks, GapFillMode.NONE)

    def test_multi_channel_interpolate(self):
        """Multi-channel interpolation applies per channel independently.

        2 channels, 2 samples per chunk.
        Channel 0: trailing=4.0, leading=10.0 → delta=6.0
        Channel 1: trailing=20.0, leading=8.0 → delta=-12.0
        Gap = 1 chunk × 2 samples = 2 positions, divisor = 3.
        """
        chunk0 = _make_chunk(0, np.array([
            [1.0, 4.0],
            [10.0, 20.0],
        ]))
        chunk2 = _make_chunk(2, np.array([
            [10.0, 13.0],
            [8.0, 5.0],
        ]))
        filled, gap, _ = sort_and_fill_chunks(
            [chunk0, chunk2], GapFillMode.INTERPOLATE
        )
        assert gap
        assert len(filled) == 3

        fill = filled[1]
        assert fill.channel_count == 2
        assert fill.samples.shape == (2, 2)

        # Channel 0: 4.0 + 6.0 * 1/3 = 6.0, 4.0 + 6.0 * 2/3 = 8.0
        np.testing.assert_allclose(fill.samples[0], [6.0, 8.0])
        # Channel 1: 20.0 + (-12.0) * 1/3 = 16.0, 20.0 + (-12.0) * 2/3 = 12.0
        np.testing.assert_allclose(fill.samples[1], [16.0, 12.0])

    def test_empty_input(self):
        """Empty chunk list returns empty with no gap or reorder."""
        filled, gap, reordered = sort_and_fill_chunks([], GapFillMode.ZERO)
        assert filled == []
        assert not gap
        assert not reordered

    def test_single_chunk(self):
        """Single chunk is returned as-is with no gap or reorder."""
        chunk = _make_chunk(5, np.array([[42.0, 43.0]]))
        filled, gap, reordered = sort_and_fill_chunks([chunk], GapFillMode.ZERO)
        assert len(filled) == 1
        assert filled[0].chunk_number == 5
        assert not gap
        assert not reordered

    def test_backward_compat_import(self):
        """GapFillMode is importable from pybrid.native for backward compat."""
        from pybrid.native import GapFillMode as NativeGapFillMode

        assert NativeGapFillMode is GapFillMode
        assert NativeGapFillMode.NONE == 0
        assert NativeGapFillMode.INTERPOLATE == 3

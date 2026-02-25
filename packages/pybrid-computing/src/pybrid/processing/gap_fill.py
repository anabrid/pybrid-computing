"""Gap detection and filling for out-of-order or missing sample chunks.

After a run completes, the Python session layer buffers all decoded sample
blobs as :class:`ChunkRecord` objects.  This module sorts them by chunk
number, detects gaps (missing chunks) and reordering, and fills the gaps
according to the selected :class:`GapFillMode`.
"""

from __future__ import annotations

import logging
import enum
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)

class GapFillMode(enum.IntEnum):
    """Strategy for filling gaps in chunk sequences.

    When a chunk gap is detected (missing UDP packets), this enum controls
    how the missing data is reconstructed:

    - **NONE**: No gap filling; raises ``RuntimeError``.
    - **ZERO**: Fill with zeros.
    - **REPEAT**: Fill every sample position with the trailing value of the
      previous chunk (per channel).
    - **INTERPOLATE**: Linear ramp from trailing values of the previous chunk
      to leading values of the next chunk across the entire gap.
    """

    NONE = 0
    ZERO = 1
    REPEAT = 2
    INTERPOLATE = 3


@dataclass(frozen=True, slots=True)
class ChunkRecord:
    """A single decoded sample chunk with metadata.

    Attributes:
        chunk_number: Sequence number from the protobuf message.
        entity_path: Entity path string (e.g. ``"/MAC/Carrier0"``).
        sample_type: Sample type: 0 = OP, 1 = OP_END.
        channel_count: Number of channels in the samples array.
        samples: Decoded samples, shape ``(channel_count, sample_count)``.
    """

    chunk_number: int
    entity_path: str
    sample_type: int
    channel_count: int
    samples: np.ndarray


def sort_and_fill_chunks(
    chunks: list[ChunkRecord],
    gap_fill_mode: GapFillMode,
) -> tuple[list[ChunkRecord], bool, bool]:
    """Sort chunks by number, detect gaps and reordering, fill according to mode.

    Args:
        chunks: List of :class:`ChunkRecord` objects (may be out of order).
        gap_fill_mode: Strategy for handling detected gaps.

    Returns:
        A tuple of ``(filled_chunks, gap_detected, reordered)`` where:

        - *filled_chunks* is the sorted list with synthetic fill chunks
          inserted for any gaps.
        - *gap_detected* is ``True`` if at least one gap was found.
        - *reordered* is ``True`` if the input order differed from sorted order.

    Raises:
        RuntimeError: If *gap_fill_mode* is :attr:`GapFillMode.NONE` and a gap
            is found.
    """
    if len(chunks) <= 1:
        return list(chunks), False, False

    sorted_chunks = sorted(chunks, key=lambda c: c.chunk_number)

    reordered = any(
        a.chunk_number != b.chunk_number
        for a, b in zip(chunks, sorted_chunks)
    )

    gap_detected = False
    result: list[ChunkRecord] = [sorted_chunks[0]]

    for i in range(1, len(sorted_chunks)):
        prev = sorted_chunks[i - 1]
        curr = sorted_chunks[i]
        gap_count = curr.chunk_number - prev.chunk_number - 1

        if gap_count > 0:
            gap_detected = True

            if gap_fill_mode == GapFillMode.NONE:
                raise RuntimeError(
                    f"Chunk gap detected: expected chunk "
                    f"{prev.chunk_number + 1} but received "
                    f"{curr.chunk_number} for entity {prev.entity_path}."
                )
            else:
                logger.warning(
                    f"Chunk gap detected: expected chunk "
                    f"{prev.chunk_number + 1} but received "
                    f"{curr.chunk_number} for entity {prev.entity_path}."
                )

            fill_chunks = _generate_fill_chunks(
                prev, curr, gap_count, gap_fill_mode,
            )
            result.extend(fill_chunks)

        result.append(curr)

    return result, gap_detected, reordered


def _generate_fill_chunks(
    prev: ChunkRecord,
    next_chunk: ChunkRecord,
    gap_count: int,
    mode: GapFillMode,
) -> list[ChunkRecord]:
    """Generate synthetic fill chunks for a gap between *prev* and *next_chunk*."""
    ch = prev.channel_count
    samples_per_chunk = prev.samples.shape[1] if prev.samples.ndim == 2 else 0

    if samples_per_chunk == 0:
        return []

    fills: list[ChunkRecord] = []

    if mode == GapFillMode.ZERO:
        zeros = np.zeros((ch, samples_per_chunk), dtype=np.float64)
        for k in range(gap_count):
            fills.append(ChunkRecord(
                chunk_number=prev.chunk_number + 1 + k,
                entity_path=prev.entity_path,
                sample_type=prev.sample_type,
                channel_count=ch,
                samples=zeros.copy(),
            ))

    elif mode == GapFillMode.REPEAT:
        trailing = prev.samples[:, -1:]  # shape (ch, 1)
        repeated = np.broadcast_to(trailing, (ch, samples_per_chunk)).copy()
        for k in range(gap_count):
            fills.append(ChunkRecord(
                chunk_number=prev.chunk_number + 1 + k,
                entity_path=prev.entity_path,
                sample_type=prev.sample_type,
                channel_count=ch,
                samples=repeated.copy(),
            ))

    else:
        # INTERPOLATE: linear ramp from prev trailing to next leading.
        # Global position p (0-based) gets:
        #   prev_trailing + (next_leading - prev_trailing) * (p+1) / (G+1)
        # where G = total_gap_samples.
        prev_trailing = prev.samples[:, -1]
        next_leading = next_chunk.samples[:, 0]

        total_gap_samples = gap_count * samples_per_chunk
        delta = next_leading - prev_trailing

        global_pos = 0
        for k in range(gap_count):
            chunk_samples = np.empty((ch, samples_per_chunk), dtype=np.float64)
            for s in range(samples_per_chunk):
                t = (global_pos + 1) / (total_gap_samples + 1)
                chunk_samples[:, s] = prev_trailing + delta * t
                global_pos += 1

            fills.append(ChunkRecord(
                chunk_number=prev.chunk_number + 1 + k,
                entity_path=prev.entity_path,
                sample_type=prev.sample_type,
                channel_count=ch,
                samples=chunk_samples,
            ))

    return fills

# Copyright (c) 2022-2025 anabrid GmbH
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
Unit tests for the decode_data function.

Tests cover all numeric dtypes, channel/sample reshaping, gain/offset scaling,
index reordering, and edge cases like empty data and unknown types.
"""

import numpy as np
import pytest

from pybrid.redac.controller import decode_data
from tests.conftest import make_daq_data


# =============================================================================
# TestDecodeDataTypes - Test all numeric dtypes
# =============================================================================

class TestDecodeDataTypes:
    """Test decode_data with various numeric dtypes."""

    @pytest.mark.parametrize("dtype,values,expected", [
        # Unsigned integers
        ("uint8", [0, 127, 255, 42], [0, 127, 255, 42]),
        ("uint16", [0, 32767, 65535, 1000], [0, 32767, 65535, 1000]),
        ("uint32", [0, 100000, 2147483647, 12345], [0, 100000, 2147483647, 12345]),
        # Signed integers
        ("int8", [-128, 0, 127, -1], [-128, 0, 127, -1]),
        ("int16", [-32768, 0, 32767, -100], [-32768, 0, 32767, -100]),
        ("int32", [-2147483648, 0, 2147483647, -12345], [-2147483648, 0, 2147483647, -12345]),
        # Floating point
        ("float32", [0.0, 1.5, -3.14, 100.25], [0.0, 1.5, -3.14, 100.25]),
        ("float64", [0.0, 1.5e-10, -3.14159265359, 1e15], [0.0, 1.5e-10, -3.14159265359, 1e15]),
    ])
    def test_decode_dtype(self, dtype, values, expected):
        """Test decoding for various numeric dtypes with identity scaling."""
        channel_count = 2
        sample_count = 2
        # Create data in Fortran order: column-major (channels vary fastest)
        # For Fortran order reshape, data layout is [ch0_s0, ch1_s0, ch0_s1, ch1_s1]
        data_pb = make_daq_data(
            values=values,
            dtype=dtype,
            channel_count=channel_count,
            sample_count=sample_count
        )

        result = decode_data(data_pb)

        # Verify shape
        assert result.shape == (channel_count, sample_count)
        # Verify values (with tolerance for floats)
        expected_arr = np.array(values, dtype=dtype).reshape(
            channel_count, sample_count, order='F'
        ).astype(float)  # decode_data applies scaling, result is float
        np.testing.assert_allclose(result, expected_arr, rtol=1e-6)


# =============================================================================
# TestDecodeDataReshaping - Test channel/sample reshaping
# =============================================================================

class TestDecodeDataReshaping:
    """Test data reshaping for various channel and sample configurations."""

    def test_single_channel(self):
        """Test decoding with a single channel."""
        values = [1, 2, 3, 4, 5]
        data_pb = make_daq_data(
            values=values,
            dtype="int16",
            channel_count=1,
            sample_count=5
        )

        result = decode_data(data_pb)

        assert result.shape == (1, 5)
        np.testing.assert_array_equal(result[0], [1, 2, 3, 4, 5])

    def test_multiple_channels(self):
        """Test decoding with multiple channels."""
        # Fortran order: [ch0_s0, ch1_s0, ch2_s0, ch0_s1, ch1_s1, ch2_s1, ...]
        # 3 channels, 4 samples
        values = [
            1, 2, 3,   # sample 0: ch0=1, ch1=2, ch2=3
            4, 5, 6,   # sample 1: ch0=4, ch1=5, ch2=6
            7, 8, 9,   # sample 2: ch0=7, ch1=8, ch2=9
            10, 11, 12  # sample 3: ch0=10, ch1=11, ch2=12
        ]
        data_pb = make_daq_data(
            values=values,
            dtype="int16",
            channel_count=3,
            sample_count=4
        )

        result = decode_data(data_pb)

        assert result.shape == (3, 4)
        # Channel 0: samples [1, 4, 7, 10]
        np.testing.assert_array_equal(result[0], [1, 4, 7, 10])
        # Channel 1: samples [2, 5, 8, 11]
        np.testing.assert_array_equal(result[1], [2, 5, 8, 11])
        # Channel 2: samples [3, 6, 9, 12]
        np.testing.assert_array_equal(result[2], [3, 6, 9, 12])

    def test_single_sample_single_channel(self):
        """Test the minimal case: 1 channel, 1 sample."""
        data_pb = make_daq_data(
            values=[42],
            dtype="int16",
            channel_count=1,
            sample_count=1
        )

        result = decode_data(data_pb)

        assert result.shape == (1, 1)
        assert result[0, 0] == 42

    def test_fortran_order_preserved(self):
        """Verify that Fortran (column-major) ordering is correctly applied."""
        # 2 channels, 3 samples in Fortran order
        # Memory layout: [ch0_s0, ch1_s0, ch0_s1, ch1_s1, ch0_s2, ch1_s2]
        values = [10, 20, 11, 21, 12, 22]
        data_pb = make_daq_data(
            values=values,
            dtype="int16",
            channel_count=2,
            sample_count=3
        )

        result = decode_data(data_pb)

        assert result.shape == (2, 3)
        # Channel 0 should have [10, 11, 12]
        np.testing.assert_array_equal(result[0], [10, 11, 12])
        # Channel 1 should have [20, 21, 22]
        np.testing.assert_array_equal(result[1], [20, 21, 22])


# =============================================================================
# TestDecodeDataScaling - Test gain, offset, reordering
# =============================================================================

class TestDecodeDataScaling:
    """Test scaling operations: gain, offset, and index reordering."""

    def test_identity_scaling(self):
        """Test that identity scaling (gain=1, offset=0) preserves values."""
        values = [100, 200, 150, 250]
        data_pb = make_daq_data(
            values=values,
            dtype="int16",
            channel_count=2,
            sample_count=2,
            scaling=[(0, 1.0, 0.0), (1, 1.0, 0.0)]
        )

        result = decode_data(data_pb)

        expected = np.array(values, dtype='int16').reshape(2, 2, order='F')
        np.testing.assert_array_equal(result, expected)

    def test_gain_scaling(self):
        """Test that gain scaling multiplies values correctly."""
        # 2 channels, 2 samples
        values = [10, 20, 30, 40]
        data_pb = make_daq_data(
            values=values,
            dtype="int16",
            channel_count=2,
            sample_count=2,
            scaling=[
                (0, 2.0, 0.0),  # Channel 0: gain=2
                (1, 0.5, 0.0)  # Channel 1: gain=0.5
            ]
        )

        result = decode_data(data_pb)

        # Original shape after reshape (Fortran order):
        # Channel 0: [10, 30], Channel 1: [20, 40]
        # After gain: Channel 0: [20, 60], Channel 1: [10, 20]
        np.testing.assert_array_equal(result[0], [20, 60])
        np.testing.assert_array_equal(result[1], [10, 20])

    def test_offset_scaling(self):
        """Test that offset scaling adds values correctly."""
        values = [10, 20, 30, 40]
        data_pb = make_daq_data(
            values=values,
            dtype="int16",
            channel_count=2,
            sample_count=2,
            scaling=[
                (0, 1.0, 100.0),  # Channel 0: offset=100
                (1, 1.0, -50.0)  # Channel 1: offset=-50
            ]
        )

        result = decode_data(data_pb)

        # Original: Channel 0: [10, 30], Channel 1: [20, 40]
        # After offset: Channel 0: [110, 130], Channel 1: [-30, -10]
        np.testing.assert_array_equal(result[0], [110, 130])
        np.testing.assert_array_equal(result[1], [-30, -10])

    def test_combined_gain_offset(self):
        """Test combined gain and offset scaling: result = data * gain + offset."""
        values = [10, 20, 30, 40]
        data_pb = make_daq_data(
            values=values,
            dtype="int16",
            channel_count=2,
            sample_count=2,
            scaling=[
                (0, 2.0, 5.0),   # Channel 0: value*2 + 5
                (1, 0.1, 100.0)  # Channel 1: value*0.1 + 100
            ]
        )

        result = decode_data(data_pb)

        # Original: Channel 0: [10, 30], Channel 1: [20, 40]
        # After scaling: Channel 0: [10*2+5=25, 30*2+5=65]
        #                Channel 1: [20*0.1+100=102, 40*0.1+100=104]
        np.testing.assert_allclose(result[0], [25.0, 65.0])
        np.testing.assert_allclose(result[1], [102.0, 104.0])

    def test_index_reordering(self):
        """Test that scaling index reorders channels correctly."""
        # 3 channels, 2 samples
        # Fortran order: [ch0_s0, ch1_s0, ch2_s0, ch0_s1, ch1_s1, ch2_s1]
        values = [1, 2, 3, 4, 5, 6]
        data_pb = make_daq_data(
            values=values,
            dtype="int16",
            channel_count=3,
            sample_count=2,
            scaling=[
                # Reorder: output[0] = input[2], output[1] = input[0], output[2] = input[1]
                (2, 1.0, 0.0),  # First output channel comes from input channel 2
                (0, 1.0, 0.0),  # Second output channel comes from input channel 0
                (1, 1.0, 0.0)   # Third output channel comes from input channel 1
            ]
        )

        result = decode_data(data_pb)

        # Original after reshape:
        # input[0]: [1, 4], input[1]: [2, 5], input[2]: [3, 6]
        # Reordered via indices:
        # output[0] = input[2] = [3, 6]
        # output[1] = input[0] = [1, 4]
        # output[2] = input[1] = [2, 5]
        assert result.shape == (3, 2)
        np.testing.assert_array_equal(result[0], [3, 6])
        np.testing.assert_array_equal(result[1], [1, 4])
        np.testing.assert_array_equal(result[2], [2, 5])

    def test_scaling_with_float_data(self):
        """Test scaling applied to floating-point input data."""
        values = [1.5, 2.5, 3.5, 4.5]
        data_pb = make_daq_data(
            values=values,
            dtype="float32",
            channel_count=2,
            sample_count=2,
            scaling=[
                (0, 10.0, 0.5),  # Channel 0: value*10 + 0.5
                (1, 10.0, 0.5)  # Channel 1: value*10 + 0.5
            ]
        )

        result = decode_data(data_pb)

        # Original: Channel 0: [1.5, 3.5], Channel 1: [2.5, 4.5]
        # After scaling: Channel 0: [15.5, 35.5], Channel 1: [25.5, 45.5]
        np.testing.assert_allclose(result[0], [15.5, 35.5], rtol=1e-5)
        np.testing.assert_allclose(result[1], [25.5, 45.5], rtol=1e-5)


# =============================================================================
# TestDecodeDataEdgeCases - Test empty data and unknown types
# =============================================================================

class TestDecodeDataEdgeCases:
    """Test edge cases and error handling in decode_data."""

    def test_empty_data(self):
        """Test decoding with zero samples returns correctly shaped empty array."""
        # Create a DaqData with 0 samples
        data_pb = make_daq_data(
            values=[],
            dtype="int16",
            channel_count=2,
            sample_count=0,
            scaling=[(0, 1.0, 0.0), (1, 1.0, 0.0)]
        )

        result = decode_data(data_pb)

        # Empty data should reshape to (2, 0) and remain empty after scaling
        assert result.shape == (2, 0)
        assert result.size == 0

    def test_unknown_type_returns_empty(self):
        """Test that unknown data type returns an empty array."""
        import pybrid.base.proto.main_pb2 as pb

        # Create a DaqData with no type set (neither integer nor float_)
        data_pb = pb.DaqData()
        data_pb.channel_count = 2
        data_pb.sample_count = 2
        data_pb.data = b'\x00\x00\x00\x00'  # Some arbitrary bytes
        # Note: we do NOT set data_pb.type, so kind will be None

        result = decode_data(data_pb)

        # Should return empty array with None dtype
        assert isinstance(result, np.ndarray)
        assert result.size == 0

    def test_large_sample_count(self):
        """Test decoding with a large number of samples."""
        sample_count = 10000
        channel_count = 4
        values = list(range(sample_count * channel_count))

        data_pb = make_daq_data(
            values=values,
            dtype="int32",  # Use int32 to handle large values (up to 39999)
            channel_count=channel_count,
            sample_count=sample_count
        )

        result = decode_data(data_pb)

        assert result.shape == (channel_count, sample_count)
        # Verify first and last values of channel 0
        # Fortran order: channel 0 gets indices 0, 4, 8, ... (every channel_count-th value)
        expected_ch0 = list(range(0, sample_count * channel_count, channel_count))
        np.testing.assert_array_equal(result[0], expected_ch0)

    def test_negative_gain(self):
        """Test that negative gain inverts the signal."""
        values = [10, 20, 30, 40]
        data_pb = make_daq_data(
            values=values,
            dtype="int16",
            channel_count=2,
            sample_count=2,
            scaling=[
                (0, -1.0, 0.0),  # Channel 0: invert
                (1, 1.0, 0.0)   # Channel 1: normal
            ]
        )

        result = decode_data(data_pb)

        # Original: Channel 0: [10, 30], Channel 1: [20, 40]
        # After scaling: Channel 0: [-10, -30], Channel 1: [20, 40]
        np.testing.assert_array_equal(result[0], [-10, -30])
        np.testing.assert_array_equal(result[1], [20, 40])

    def test_zero_gain(self):
        """Test that zero gain produces zero output."""
        values = [100, 200, 300, 400]
        data_pb = make_daq_data(
            values=values,
            dtype="int16",
            channel_count=2,
            sample_count=2,
            scaling=[
                (0, 0.0, 50.0),  # Channel 0: zero gain, offset only
                (1, 1.0, 0.0)   # Channel 1: normal
            ]
        )

        result = decode_data(data_pb)

        # Channel 0 should be all 50.0 (0 * value + 50)
        np.testing.assert_array_equal(result[0], [50, 50])
        # Channel 1 should be original values
        np.testing.assert_array_equal(result[1], [200, 400])

#pragma once

#include <cstddef>
#include <cstdint>

namespace anabrid::pybrid::native {

/// A 64-bit value requires at most ceil(64/7) = 10 bytes in varint encoding.
constexpr size_t MAX_VARINT_SIZE = 10;

/**
 * @brief Encode a 64-bit unsigned integer as a varint.
 *
 * Standard varint encoding (compatible with Protocol Buffers):
 * each byte stores 7 bits, high bit (0x80) indicates continuation, LSB first.
 *
 * @param value The value to encode.
 * @param buf Output buffer (must have at least MAX_VARINT_SIZE bytes).
 * @return Number of bytes written (1-10).
 */
inline size_t encode_varint(uint64_t value, uint8_t* buf) {
    size_t i = 0;
    while (value >= 0x80) {
        buf[i++] = static_cast<uint8_t>((value & 0x7F) | 0x80);
        value >>= 7;
    }
    buf[i++] = static_cast<uint8_t>(value & 0x7F);
    return i;
}

/**
 * @brief Decode a varint from a byte buffer.
 *
 * @param buf Input buffer containing the varint.
 * @param len Length of the input buffer.
 * @param out Output parameter for the decoded value.
 * @return Number of bytes consumed (1-10), or 0 if incomplete or overflow.
 */
inline size_t decode_varint(const uint8_t* buf, size_t len, uint64_t& out) {
    out = 0;
    for (size_t i = 0; i < len && i < MAX_VARINT_SIZE; ++i) {
        out |= static_cast<uint64_t>(buf[i] & 0x7F) << (7 * i);
        if (!(buf[i] & 0x80)) {
            return i + 1;
        }
    }
    return 0;  // Incomplete or overflow
}

/// @return Number of bytes needed to encode the value (1-10).
inline size_t varint_size(uint64_t value) {
    size_t size = 1;
    while (value >= 0x80) {
        ++size;
        value >>= 7;
    }
    return size;
}

}  // namespace anabrid::pybrid::native

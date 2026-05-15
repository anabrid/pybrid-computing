import hashlib
import io
from pathlib import Path
from typing import Tuple

# Intel HEX record kinds (values mirror the C++ ``Kind`` enum in the native
# updater).
_HEX_KIND_DATA = 0x00
_HEX_KIND_EOF = 0x01
_HEX_KIND_EXT_SEG_ADDR = 0x02
_HEX_KIND_EXT_LIN_ADDR = 0x04
_HEX_KIND_START_LIN_ADDR = 0x05

# FlexSPI flash base address for Teensy 4.x firmware images. Firmware records
# are emitted at absolute addresses starting here and are rebased to zero in
# the resulting binary image.
FW_BASE_ADDR = 0x60000000

# Maximum firmware image size accepted by the bootloader.
FW_MAX_SIZE = 0x37F000

# Whitespace byte values skipped between records (matches std::isspace).
_HEX_WHITESPACE = frozenset((0x20, 0x09, 0x0A, 0x0B, 0x0C, 0x0D))


def _decode_nibble(value: int) -> int:
    """Decode a single ASCII hex digit to its 4-bit value."""
    if 0x30 <= value <= 0x39:  # '0'-'9'
        return value - 0x30
    if 0x41 <= value <= 0x46:  # 'A'-'F'
        return value - 0x41 + 10
    if 0x61 <= value <= 0x66:  # 'a'-'f'
        return value - 0x61 + 10
    raise ValueError(f"Invalid hex digit: {value:#04x}")


def hex2bin(hex_data: bytes | bytearray) -> bytearray:
    """
    Convert an Intel HEX firmware image (as raw bytes) into its binary
    representation, rebased to ``FW_BASE_ADDR``.

    Mirrors the semantics of the ``hex2bin`` helper in the native updater:
    records are parsed sequentially, checksums are verified, and data bytes
    are written to a buffer indexed by ``current_addr + addr - FW_BASE_ADDR``.
    Returns an empty bytearray on any parse error, checksum mismatch,
    unknown record type, or if the end-of-file record is never encountered.
    """
    result = bytearray()
    buffer = bytearray(256)
    current_addr = 0
    idx = 0
    length = len(hex_data)

    def decode_8(i: int) -> tuple[int, int]:
        return (_decode_nibble(hex_data[i]) << 4) + _decode_nibble(hex_data[i + 1]), i + 2

    def decode_16(i: int) -> tuple[int, int]:
        hi, i = decode_8(i)
        lo, i = decode_8(i)
        return (hi << 8) + lo, i

    try:
        while idx < length:
            colon = hex_data[idx]
            idx += 1
            if colon in _HEX_WHITESPACE:
                continue
            if colon != 0x3A:  # ':'
                return bytearray()

            bytes_count, idx = decode_8(idx)
            addr, idx = decode_16(idx)
            kind, idx = decode_8(idx)

            for buf_idx in range(bytes_count):
                buffer[buf_idx], idx = decode_8(idx)

            checksum, idx = decode_8(idx)

            # Intel HEX checksum: two's complement of the sum of all record
            # bytes, so summing every field together (including the checksum
            # itself) must yield 0 mod 256.
            record_sum = bytes_count + (addr >> 8) + (addr & 0xFF) + kind
            for i in range(bytes_count):
                record_sum += buffer[i]
            record_sum += checksum
            if record_sum & 0xFF:
                return bytearray()

            if kind == _HEX_KIND_EOF:
                return result
            elif kind == _HEX_KIND_EXT_LIN_ADDR:
                current_addr = ((buffer[0] << 8) | buffer[1]) << 16
            elif kind == _HEX_KIND_DATA:
                if current_addr < FW_BASE_ADDR:
                    return bytearray()
                full_addr = current_addr + addr - FW_BASE_ADDR
                end = full_addr + bytes_count
                if end > len(result):
                    result.extend(b"\x00" * (end - len(result)))
                result[full_addr:end] = buffer[:bytes_count]
            elif kind == _HEX_KIND_START_LIN_ADDR:
                # Start linear address records carry the entry point; the
                # bootloader ignores them, so we skip without error.
                pass
            else:
                return bytearray()
    except (IndexError, ValueError):
        return bytearray()

    # No EOF record encountered.
    return bytearray()


class UpdaterUtils:
    """
    Collection of utilities for dealing with device firmware files (starting
    from text files in .hex) form.
    """

    @staticmethod
    def sha256(input: bytearray) -> bytes:
        obj = hashlib.sha256()
        obj.update(input)
        return obj.digest()

    @staticmethod
    def read_to_bin(filename: str) -> Tuple[bytearray, bytes]:
        """
        Read an Intel HEX firmware file from disk and return the binary image
        ready for OTA upload (rebased to ``FW_BASE_ADDR``).
        """
        if not Path(filename).exists():
            raise Exception(f"Unable to find firmware at {filename}")

        with open(filename, "rb") as f:
            firmware_hex = bytearray(f.read())

        firmware_bin = hex2bin(firmware_hex)
        if not firmware_bin:
            raise Exception(f"Unable to convert firmware at {filename} to binary format")
        return (firmware_bin, UpdaterUtils.sha256(firmware_bin))

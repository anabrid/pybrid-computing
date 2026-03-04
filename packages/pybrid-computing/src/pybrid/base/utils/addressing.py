from typing import Dict, Optional, Callable
import warnings
import pybrid.base.proto.main_pb2 as pb

from pybrid.redac.computer import REDAC

class AddressingMap:
    """Linearized mapping schemes for REDAC/LUCIStack address mappings."""

    @staticmethod
    def map_lucistack(ix: int) -> Optional[str]:
        if ix < 256:
            return f"00-00-00-00-00-{ix:02x}"

        return None

    @staticmethod
    def index_of_redac(mac: str) -> Optional[int]:
        """Reverse lookup: return the linear index of a virtual REDAC address, or None."""
        for ix in range(12):
            if AddressingMap.map_redac(ix) == mac:
                return ix
        return None

    @staticmethod
    def map_redac(ix: int) -> Optional[str]:
        _VIRTUAL_ADDRESSES = [
            "00-00-00-00-00-00",
            "00-00-00-00-00-01",
            "00-00-00-00-00-02",
            "00-00-01-00-00-00",
            "00-00-01-00-00-01",
            "00-00-01-00-00-02",
            "01-00-00-00-00-00",
            "01-00-00-00-00-01",
            "01-00-00-00-00-02",
            "01-00-01-00-00-00",
            "01-00-01-00-00-01",
            "01-00-01-00-00-02"
        ]

        if ix < len(_VIRTUAL_ADDRESSES):
            return _VIRTUAL_ADDRESSES[ix]

        return None

class Addressing:
    """Converts between physical and virtual addressing schemes.

    Primarily used for operating LUCIDACs (physical MACs) through REDAC
    (virtual MACs).
    """

    @classmethod
    def is_physical_mac(cls, mac: str) -> bool:
        """Check MAC against the anabrid hardware prefix."""
        return mac.startswith("04-E9-E5")

    @classmethod
    def has_physical_addresses(cls, file: pb.File) -> bool:
        """Return True if any config path in *file* uses a physical MAC."""
        for config in file.bundle.configs:
            path = config.entity.path

            if len(path) == 0:
                continue

            # leading slash generates empty string as first array member
            use_ix = 1 if path.startswith("/") else 0
            carrier = path.split("/")[use_ix]
            if Addressing.is_physical_mac(carrier):
                return True

        return False

    @classmethod
    def _map(cls, file: pb.File, map: Dict[str, str]):
        """Apply address substitution map to a copy of *file*."""
        new_file = pb.File()
        new_file.CopyFrom(file)

        for config in new_file.bundle.configs:
            path = config.entity.path

            if len(path) == 0:
                continue

            # leading slash generates empty string as first array member
            use_ix = 1 if path.startswith("/") else 0
            parts = path.split("/")

            if parts[use_ix] in map: 
                parts[use_ix] = map[parts[use_ix]]
            else:
                raise Exception(f"Unable to map address {parts[use_ix]}")

            config.entity.path = "/".join(parts)

        return new_file

    @classmethod
    def physical_to_virtual(cls, computer: REDAC, file: pb.File,
        map: Callable = AddressingMap.map_redac) -> pb.File:
        """Convert physical addresses to virtual by linear carrier order.

        Assumes physical carriers in *computer* match the order in the
        virtual address table.

        .. deprecated:: Use physical addresses directly.
        """
        warnings.warn(
            "Addressing.physical_to_virtual() is deprecated. Use physical addresses "
            "directly instead of converting back from physical to virtual.",
            DeprecationWarning,
            stacklevel=2,
        )

        if not cls.has_physical_addresses(file):
            return file

        linear_map = {}

        for ix, carrier in enumerate(computer.entities):
            linear_map[carrier.path.to_mac()] = map(ix)

        return cls._map(file, linear_map)

    @classmethod
    def remap_virtual_mac(cls, pb_file: pb.File, target_mac: str) -> pb.File:
        """Replace ``00-00-00-00-00-00`` with *target_mac* in all config paths.

        Unlike ``virtual_to_physical`` which maps all known virtual addresses,
        this helper only targets the default virtual MAC and is intended for
        per-circuit translation when building multi-device config bundles.
        """
        return cls._map(pb_file, {"00-00-00-00-00-00": target_mac})

    @classmethod
    def virtual_to_physical(cls, computer: REDAC, file: pb.File,
        map: Callable = AddressingMap.map_redac) -> pb.File:
        """Convert virtual addresses to physical by linear carrier order.

        .. deprecated:: Use physical addresses directly or ``--portable-map``.
        """
        warnings.warn(
            "Addressing.virtual_to_physical() is deprecated. Use --portable-map for "
            "explicit virtual-to-physical mapping, or use physical addresses directly.",
            DeprecationWarning,
            stacklevel=2,
        )

        if cls.has_physical_addresses(file):
            return file

        linear_map = {}

        for ix, carrier in enumerate(computer.entities):
            linear_map[map(ix)] = carrier.path.to_mac()

        return cls._map(file, linear_map)

from typing import Dict, Optional, Callable
import pybrid.base.proto.main_pb2 as pb

from pybrid.redac.computer import REDAC

class AddressingMap:
    """
    Defines linearized mapping schemes for REDAC/LUCIStack address mappings.
    """

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
    """
    Class to convert between physical and virtual addrssing schemes Mostly used
    for operating LUCIDACs (expecting physical MACs) through REDAC (expecting
    virtual MACs).
    """

    @classmethod
    def is_physical_mac(cls, mac: str) -> bool:
        """
        Checks MACs against anabrid prefix.
        """
    
        return mac.startswith("04-E9-E5")

    @classmethod
    def has_physical_addresses(cls, file: pb.File) -> bool:
        """Checks whether a configuration uses physical addresses"""
        
        for config in file.bundle.configs:
            path = config.entity.path

            if len(path) == 0:
                # global configs outside of the entity path system, e.g. config
                continue

            carrier = path.split("/")[0]
            if Addressing.is_physical_mac(carrier):
                return True
            
        return False
    
    @classmethod
    def _map(cls, file: pb.File, map: Dict[str, str]):
        """Internal procedure doing the mapping."""

        # replace IDs in copy of message
        new_file = pb.File()
        new_file.CopyFrom(file)

        for config in new_file.bundle.configs:
            path = config.entity.path

            if len(path) == 0:
                # global configs outside of the entity path system, e.g. config
                continue

            parts = path.split("/")
            if parts[0] in map:
                parts[0] = map[parts[0]]
            else:
                raise Exception(f"Unable to map address {parts[0]}")
            
            config.entity.path = "/".join(parts)

        return new_file
            
    @classmethod
    def physical_to_virtual(cls, computer: REDAC, file: pb.File,
        map: Callable = AddressingMap.map_redac) -> pb.File:
        """
        Converts a config with physical addresses by linear mapping of
        physical addresses to virtual addresses. 

        Assumes that the order physical addresses (Carrier) in the computer
        object conforms to the order in VIRTUAL_ADDRESSES as above.
        """

        if not cls.has_physical_addresses(file):
            return file
        
        # produce linear map of physical to virtual addresses
        linear_map = {}

        for ix, carrier in enumerate(computer.entities):
            linear_map[carrier.path.to_mac()] = map(ix)

        return cls._map(file, linear_map)

    @classmethod
    def remap_virtual_mac(cls, pb_file: pb.File, target_mac: str) -> pb.File:
        """Replace all occurrences of 00-00-00-00-00-00 with target_mac in config paths.

        Unlike ``virtual_to_physical`` which maps all known virtual addresses,
        this helper only targets the default virtual MAC (``00-00-00-00-00-00``)
        and is intended for per-circuit translation when building multi-device
        config bundles.

        Args:
            pb_file: Protobuf File with configs to remap.
            target_mac: Physical MAC string to substitute
                (e.g., ``"AB-CD-EF-12-34-56"``).

        Returns:
            A new pb.File with all matching paths remapped.
        """
        return cls._map(pb_file, {"00-00-00-00-00-00": target_mac})

    @classmethod
    def virtual_to_physical(cls, computer: REDAC, file: pb.File,
        map: Callable = AddressingMap.map_redac) -> pb.File:
        """
        Converts a config with virtual addresses by linear mapping of the carriers
        in a computer object to physical addresses.

        Note that in a production setup, this is a step that would be done on-the-fly
        by the supercontroller, at which point a customizable mapping may be employed.
        """
        
        if cls.has_physical_addresses(file):
            return file
        
        # produce linear map of virtual to physical address
        linear_map = {}

        for ix, carrier in enumerate(computer.entities):
            linear_map[map(ix)] = carrier.path.to_mac()

        return cls._map(file, linear_map)

    
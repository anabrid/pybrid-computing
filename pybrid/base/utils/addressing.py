from typing import Dict
import pybrid.base.proto.main_pb2 as pb

from pybrid.redac.computer import REDAC

class Addressing:
    """
    Class to convert between physical and virtual addrssing schemes Mostly used
    for operating LUCIDACs (expecting physical MACs) through REDAC (expecting
    virtual MACs).
    """

    # note: this is the current REDAC configuration and will likely
    # change in the future
    VIRTUAL_ADRESSES = [
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

    @classmethod
    def has_physical_addresses(cls, file: pb.File) -> bool:
        """Checks whether a configuration uses physical addresses"""
        
        for config in file.bundle.configs:
            path = config.entity.path

            if len(path) == 0:
                # global configs outside of the entity path system, e.g. config
                continue

            carrier = path.split("/")[0]
            if carrier not in cls.VIRTUAL_ADRESSES:
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
    def physical_to_virtual(cls, computer: REDAC, file: pb.File) -> pb.File:
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
            linear_map[carrier.path.to_mac()] = cls.VIRTUAL_ADRESSES[ix]

        return cls._map(file, linear_map)

    @classmethod
    def virtual_to_physical(cls, computer: REDAC, file: pb.File) -> pb.File:
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
            linear_map[cls.VIRTUAL_ADRESSES[ix]] = carrier.path.to_mac()

        return cls._map(file, linear_map)

    
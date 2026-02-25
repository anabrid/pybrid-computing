from abc import ABC, abstractmethod
from typing import Union

import pybrid.base.proto.main_pb2 as pb

class UpdatePathStep(ABC):

    @abstractmethod
    def update(self, msg: pb.File | pb.Envelope) -> pb.File | pb.Envelope:
        pass

class FileUpdate_0_1_0_to_0_2_0(UpdatePathStep):
    pass

class EnvelopeUpdate_0_1_0_to_0_2_0(UpdatePathStep):
    pass

class ProtoVersioning:
    """
    This class represents the update path for protobuf-based messages following
    the REDAC protocol. Checks versions for both the File as well as the 
    Envelope message and, if the message is of an older version, tries to
    upgrade it to a newer version.
    """

    # contains a list of conversion functions, each converting an object of a
    # certain version to the next more recent version
    update_path = {
        pb.File: [
            (pb.Version(major=0, minor=1, patch=0), FileUpdate_0_1_0_to_0_2_0)
        ],
        pb.Envelope: [
            (pb.Version(major=0, minor=1, patch=0), EnvelopeUpdate_0_1_0_to_0_2_0)
        ]
    }

    @classmethod
    def is_versioned(cls, input: pb.File | pb.Envelope):
        """Checks whether a protobuf object is subject to protocol versioning"""
        return isinstance(input, pb.File) or isinstance(input, pb.Envelope)

    @classmethod
    def current(cls):
        """Return the latest - supported - version of the protobuf Message"""
        return pb.Version(
            major = 0,
            minor = 1,
            patch = 0)
    
    @classmethod
    def is_newer(cls, lhs: pb.Version, rhs: pb.Version):
        """Compares versions and returns whether lhs > rhs"""
        if lhs.major != rhs.major:
            return lhs.major > rhs.major
        
        if lhs.minor != rhs.minor:
            return lhs.minor > rhs.minor
        
        return lhs.patch > rhs.patch
    
    @classmethod
    def is_same(cls, lhs: pb.Version, rhs: pb.Version):
        """Compares two versions and checks whether they are identical."""
        return not cls.is_newer(lhs, rhs) and not \
            cls.is_newer(rhs, lhs)
    
    @classmethod
    def is_recent(cls, input: pb.File | pb.Envelope):

        if not cls.is_versioned(input):
            raise Exception("Can only detect the version of File/Envelope messages!")
        
        return not cls.is_newer(input.version, cls.current()) and not \
            cls.is_newer(cls.current(), input.version)
    
    @classmethod
    def update(cls, input: pb.File | pb.Envelope):

        cur = type(input)()
        cur.CopyFrom(input)

        while(cls.is_newer(cls.current(), cur.version)):

            # retrieve the matching converter for the current type/version
            current_converter = None
            try:
                for version, converter_t in cls.update_path[type(cur)]:
                    if cls.is_same(version, cur.version):
                        current_converter = converter_t()
                        break
            except:
                raise Exception(f"Unable to find update path for type {str(type(cur))}")
            
            if current_converter is None:
                raise Exception(f"Unable to find update path for version: {str(cur.version)}")
            
            # convert to next version
            cur = current_converter.update(cur)

        return cur
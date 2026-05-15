import logging

import pybrid.base.proto.main_pb2 as pb
from pybrid.base.proto.versioning import ProtoVersioning

logger = logging.getLogger(__name__)


class ProtoIO:
    """
    Provides IO routines for the protobuf, such as loading and storing
    protobuf files in binary (.apb) format from disk.
    """

    @classmethod
    def load_module(cls, path: str, skip_update: bool = False) -> pb.Module:
        """
        Loads a protobuf module from a .apb file and makes sure that loaded
        files conform to the latest version.
        """
        if not path.endswith(".apb"):
            raise Exception("Unknown file extension for config, only .apb is supported.")

        try:
            apb_config = pb.File()
            with open(path, "rb") as f:
                apb_config.ParseFromString(f.read())
        except Exception as e:
            raise Exception(f"Unable to read config file {path}: {e}")

        if not skip_update:
            apb_config = ProtoVersioning.update(apb_config)

        return apb_config.module

    @classmethod
    def store_module(cls, module: pb.Module, path: str, version=ProtoVersioning.current()):
        """
        Stores a pb file as .apb file (binary). Uses the latest version.
        """
        pb_file = pb.File(version=version, module=module)
        with open(path, "wb") as f:
            f.write(pb_file.SerializeToString())

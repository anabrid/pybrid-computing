import logging
import json
from typing import Dict, Any

import pybrid.base.proto.main_pb2 as pb
from pybrid.base.proto.versioning import ProtoVersioning
from google.protobuf.json_format import MessageToDict, ParseDict, ParseError

logger = logging.getLogger(__name__)

class ProtoIO:
    """
    Provides IO routines for the protobuf, such as loading protobuf files
    in both JSON and binary formats from disk and converting.
    """

    @classmethod
    def json_to_pbfile(cls, input: Dict[str, Any]) -> pb.File:
        if not "version" in input:
            raise Exception("Malformatted input module: 'version' missing!")
        if not "module" in input:
            raise Exception("Malformatted input module: 'module' missing!")
        if not "items" in input["module"]:
            raise Exception("Malformatted input module: 'module/items' missing!")
        
        # Parse each config to protobuf
        pb_file = pb.File()
        ParseDict(input, pb_file, ignore_unknown_fields=False)
    
        return pb_file

    @classmethod
    def pbfile_to_json(cls, file: pb.File) -> Dict[str, Any]:
        return MessageToDict(file, preserving_proto_field_name=True)

    @classmethod
    def json_is_pb_file(cls, input: Dict[str, Any]) -> bool:
        """
        Detect whether a given dict / JSON is of protobuf/items format
        """
        return "module" in input

    @classmethod
    def open_pb_file(cls, path: str, skip_update: bool = False) -> pb.File:
        """
        Loads a protobuf file from disk. Supports both JSON and binary representation
        and makes sure that loaded files conform to the latest version.
        """
        apb_config = None

        if path.endswith(".apb"):
            # binary protobuf-representation
            try:
                apb_config = pb.File()
                with open(path, "rb") as f:
                    apb_config.ParseFromString(f.read())

            except Exception as e:
                raise Exception(f"Unable to read config file {path}: {e}")
        
        elif path.endswith(".json"):
            # json-based config file
            try:
                with open(path, "r") as f:
                    json_config = json.load(f)

                if not cls.json_is_pb_file(json_config):
                    raise Exception("JSON-config is not a valid module - if you're using an legacy-style JSON, try pybrid convert!")
                
                apb_config = cls.json_to_pbfile(json_config)
                logger.warning("JSON-based PB format is deprecated and eventually only APB files can be loaded, please consider using APB files...")
            
            except Exception as e:
                raise Exception(f"Unable to read json-module file {path}: {e}")
            
        else:
            raise Exception("Unknown file extension for config, only .json and .apb are supported.")
        
        if not skip_update:
            apb_config = ProtoVersioning.update(apb_config)

        return apb_config
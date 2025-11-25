# Copyright (c) 2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import json
from typing import Dict, Any, List

import pybrid.base.proto.main_pb2 as pb
from google.protobuf.json_format import MessageToDict, ParseDict, ParseError

def json_to_pbfile(input: Dict[str, Any]) -> pb.File:
    if not "version" in input:
        raise Exception("Malformatted input bundle: 'version' missing!")
    if not "bundle" in input:
        raise Exception("Malformatted input bundle: 'bundle' missing!")
    if not "configs" in input["bundle"]:
        raise Exception("Malformatted input bundle: 'bundle/configs' missing!")
    
    # Parse each config to protobuf
    pb_file = pb.File()
    ParseDict(input, pb_file, ignore_unknown_fields=False)
  
    return pb_file

def pbfile_to_json(file: pb.File) -> Dict[str, Any]:
    return MessageToDict(file, preserving_proto_field_name=True)

def is_pb_file(input: Dict[str, Any]) -> bool:
    """
    Detect whether a given dict is of protobuf/bundle format
    """
    return "bundle" in input
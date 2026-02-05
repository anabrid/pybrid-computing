# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import logging
import math
import typing
import warnings
from uuid import UUID

from google.protobuf.json_format import MessageToJson

from pybrid.redac import Run, RunState
from pybrid.redac.computer import REDAC
from pybrid.redac.controller import Controller
from pybrid.redac.entities import Entity
import pybrid.base.proto.main_pb2 as pb

logger = logging.getLogger(__name__)


def _dict_to_pb_entity(id_: str, data: dict) -> pb.Entity:
    """Convert old-format dictionary to pb.Entity."""
    version = pb.Version(
        major=data["version"][0],
        minor=data["version"][1],
        patch=data["version"][2]
    )

    entity = pb.Entity(
        id=id_.lstrip('/'),
        class_=data["class"],
        type=data["type"],
        variant=data["variant"],
        version=version,
        eui=data["eui"]
    )

    # Recursively add children
    for key, value in data.items():
        if key.startswith('/'):
            child_entity = _dict_to_pb_entity(key, value)
            entity.children.append(child_entity)

    return entity


def get_dummy_computer():
    """Create a dummy REDAC computer with two carriers."""
    # Define the entity tree in old dict format
    tree_dict = {
        "/00-00-00-00-00-00": {
            "class": 1,
            "type": 1,
            "variant": 1,
            "version": [1, 0, 0],
            "eui": "00-00-00-00-00-00-00-00",
            "/0": {
                "class": 2,
                "type": 1,
                "variant": 1,
                "version": [1, 0, 0],
                "eui": "00-00-00-00-00-00-00-00",
                "/M0": {
                    "class": 3,
                    "type": 1,
                    "variant": 1,
                    "version": [1, 0, 0],
                    "eui": "00-04-A3-0B-00-16-92-1B",
                },
                "/M1": {
                    "class": 3,
                    "type": 2,
                    "variant": 1,
                    "version": [1, 0, 0],
                    "eui": "00-04-A3-0B-00-16-7D-6D",
                },
                "/U": {
                    "class": 4,
                    "type": 1,
                    "variant": 1,
                    "version": [1, 0, 0],
                    "eui": "00-04-A3-0B-00-15-76-7A",
                },
                "/C": {
                    "class": 5,
                    "type": 1,
                    "variant": 1,
                    "version": [1, 0, 0],
                    "eui": "FF-FF-D8-47-8F-3F-8E-F5",
                },
                "/I": {
                    "class": 6,
                    "type": 1,
                    "variant": 1,
                    "version": [1, 0, 0],
                    "eui": "00-04-A3-0B-00-15-3D-F5",
                },
                "/SH": {
                    "class": 7,
                    "type": 1,
                    "variant": 1,
                    "version": [1, 0, 0],
                    "eui": "00-04-A3-0B-00-16-94-9F",
                },
            },
            "/T": {
                "class": 10,
                "type": 1,
                "variant": 1,
                "version": [1, 0, 0],
                "eui": "00-04-A3-0B-00-16-7E-10",
            },
            "/CTRL": {
                "class": 9,
                "type": 1,
                "variant": 1,
                "version": [1, 0, 0],
                "eui": "00-04-A3-0B-00-16-7E-05",
            },
            "/FP": {
                "class": 8,
                "type": 1,
                "variant": 1,
                "version": [1, 0, 0],
                "eui": "00-04-A3-0B-00-14-87-29",
            },
        },
        "/00-00-00-00-00-01": {
            "class": 1,
            "type": 1,
            "variant": 1,
            "version": [1, 0, 0],
            "eui": "00-00-00-00-00-00-00-00",
            "/0": {
                "class": 2,
                "type": 1,
                "variant": 1,
                "version": [1, 0, 0],
                "eui": "00-00-00-00-00-00-00-00",
                "/M0": {
                    "class": 3,
                    "type": 1,
                    "variant": 1,
                    "version": [1, 0, 0],
                    "eui": "00-04-A3-0B-00-16-92-1B",
                },
                "/M1": {
                    "class": 3,
                    "type": 2,
                    "variant": 1,
                    "version": [1, 0, 0],
                    "eui": "00-04-A3-0B-00-16-7D-6D",
                },
                "/U": {
                    "class": 4,
                    "type": 1,
                    "variant": 1,
                    "version": [1, 0, 0],
                    "eui": "00-04-A3-0B-00-15-76-7A",
                },
                "/C": {
                    "class": 5,
                    "type": 1,
                    "variant": 1,
                    "version": [1, 0, 0],
                    "eui": "FF-FF-D8-47-8F-3F-8E-F5",
                },
                "/I": {
                    "class": 6,
                    "type": 1,
                    "variant": 1,
                    "version": [1, 0, 0],
                    "eui": "00-04-A3-0B-00-15-3D-F5",
                },
                "/SH": {
                    "class": 7,
                    "type": 1,
                    "variant": 1,
                    "version": [1, 0, 0],
                    "eui": "00-04-A3-0B-00-16-94-9F",
                },
            },
            "/T": {
                "class": 10,
                "type": 1,
                "variant": 1,
                "version": [1, 0, 0],
                "eui": "00-04-A3-0B-00-16-7E-11",
            },
            "/CTRL": {
                "class": 9,
                "type": 1,
                "variant": 1,
                "version": [1, 0, 0],
                "eui": "00-04-A3-0B-00-16-7E-05",
            },
            "/FP": {
                "class": 8,
                "type": 1,
                "variant": 1,
                "version": [1, 0, 0],
                "eui": "00-04-A3-0B-00-14-87-29",
            },
        },
    }

    # Convert dict tree to pb.Entity tree
    pb_tree = {path: _dict_to_pb_entity(path, data) for path, data in tree_dict.items()}

    return REDAC.create_from_entity_type_tree(pb_tree)


class DummyController:
    """
    Deprecated controller for testing purposes.

    .. deprecated::
        Use :class:`pybrid.mock.DummyDAC` instead for more comprehensive
        testing capabilities including error injection and run simulation.
    """

    computer: REDAC
    runs: dict[UUID, Run]

    def __init__(self):
        """Initialize the DummyController with a deprecation warning."""
        warnings.warn(
            "DummyController is deprecated. Use pybrid.mock.DummyDAC instead.",
            DeprecationWarning,
            stacklevel=2
        )
        self.computer = get_dummy_computer()
        self.runs = dict()

    async def __aenter__(self):
        # Devices are already started in add_device
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    def log_action(self, action, *args, **kwargs):
        # logger.debug("%s.%s called with args=%s, kwargs=%s", self.__class__.__name__, action, args, kwargs)
        logger.debug("%s.%s()", self.__class__.__name__, action)

    get_run_implementation = Controller.get_run_implementation

    async def forward_set_circuit(self, *args, **kwargs):
        self.log_action("forward_set_circuit", *args, **kwargs)

        async def noop():
            pass

        return noop()

    async def reset(self, *args, **kwargs):
        self.log_action("reset", *args, **kwargs)

    async def hack(self, *args, **kwargs):
        self.log_action("hack", *args, **kwargs)

    async def get_computer(self, *args, **kwargs) -> REDAC:
        self.log_action("hack", *args, **kwargs)
        return self.computer

    async def set_computer(self, *args, **kwargs):
        self.log_action("set_computer", *args, **kwargs)

        # Use the serializer to get configs
        from pybrid.redac.protocol.serializer import REDACSerializer
        serializer = REDACSerializer()
        configs = serializer.serialize(self.computer)

        logger.debug(MessageToJson(pb.ConfigCommand(bundle=pb.ConfigBundle(configs=configs))))

    async def start_run(self, *args, **kwargs):
        self.log_action("start_run", *args, **kwargs)
        raise NotImplementedError(
            "Controller.start_run() is not available in fake mode. Please only use Controller.start_and_await_run()."
        )

    async def start_and_await_run(self, run: typing.Optional[Run] = None, timeout=5) -> Run:
        self.log_action("start_and_await_run", run, timeout=timeout)
        # Add some dummy data
        run.data = {
            carrier.path.join(channel): [
                math.sin(sum(map(ord, str(carrier.path.join(channel)))) + t / 20) for t in range(0, 500)
            ]
            for channel in range(0, 2)
            for carrier in self.computer.carriers
        }
        # Return run
        run.state = RunState.DONE
        return run

    async def get_config(self, entity: Entity, *, recursive: bool = True):
        serializer_cls = self.computer.get_serializer_implementation()
        serializer = serializer_cls()

        return serializer.serialize_entities([entity])

    async def set_config(self, *args, **kwargs):
        self.log_action("set_config", *args, **kwargs)

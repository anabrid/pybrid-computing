# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import asyncio
import logging
import math
import typing
from uuid import UUID

from pybrid.redac import Run, RunState
from pybrid.redac.computer import REDAC
from pybrid.redac.controller import Controller
from pybrid.redac.entities import Entity
from pybrid.redac.protocol.messages import SetCircuitRequest
from pybrid.redac.protocol.serializer import to_pb, build_config

logger = logging.getLogger(__name__)


def get_dummy_computer():
    return REDAC.create_from_entity_type_tree(
        {
            "/04-E9-E5-15-87-C0": {
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
            "/04-E9-E5-16-08-DE": {
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
    )


class DummyController:
    computer: REDAC
    runs: dict[UUID, Run]

    def __init__(self):
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
        for carrier in self.computer.carriers:
            logger.debug(SetCircuitRequest(entity=carrier.path, config=build_config(carrier, dict())).json())

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
        entity = self.computer.get_entity(entity.path)
        return to_pb(entity)

    async def set_config(self, *args, **kwargs):
        self.log_action("set_config", *args, **kwargs)

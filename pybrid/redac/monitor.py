# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import asyncio
import json
import logging
import typing

from google.protobuf.json_format import MessageToJson

from .controller import Controller

logger = logging.getLogger(__name__)


class Monitor:
    controller: Controller
    output: typing.IO
    tasks: set[asyncio.Task]

    def __init__(self, controller, output):
        self.controller = controller
        self.output = output
        self.tasks = set()

    def start(self):
        task = asyncio.create_task(self._monitor_temperatures())
        task.add_done_callback(self.tasks.discard)
        self.tasks.add(task)

    def __await__(self):
        return asyncio.gather(*self.tasks)

    async def __aenter__(self):
        self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        for task in self.tasks:
            task.cancel()

    async def _monitor_temperatures(self):
        while True:
            logger.info("Getting current temperatures...")
            temperatures = await self.controller.get_system_temperatures()
            self.output.write(MessageToJson(temperatures))
            self.output.write("\n")
            self.output.flush()
            await asyncio.sleep(30)

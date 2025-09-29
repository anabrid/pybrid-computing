# Copyright (c) 2022-2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import asyncio
import math
from copy import deepcopy
from functools import partial
from itertools import cycle

import pytest

from pybrid.redac import Controller, REDAC, Path, Run, RunConfig
from pybrid.redac.blocks import MIntBlock, MMulBlock
from pybrid.redac.carrier import Carrier
from pybrid.redac.device import Device

sign = partial(math.copysign, 1)


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="module")
async def raw_controller():
    controller = Controller(standalone=True)
    for host, port, name in [("192.168.104.244", 5732, "00-00-00-00-00-00 15785630-Teensy")]:
        await controller.add_device(host, port, name=name)
    async with controller:
        yield controller


@pytest.fixture(scope="function")
async def controller(raw_controller):
    await raw_controller.reset()

    # TODO: Replace once entities have a proper .reset() function
    raw_controller.computer = REDAC(entities=[])
    for entity_id, sub_entities in deepcopy(raw_controller._raw_entity_dict).items():
        path = Path.parse(entity_id)
        print(path, sub_entities)
        device = Device.create_from_entity_type_tree(path, sub_entities)
        for carrier in device.carriers:
            raw_controller.computer.add_carrier(carrier)

    return raw_controller


class TestSignConvention:

    async def test_integration(self, controller: Controller):
        computer = controller.computer
        for carrier in computer.carriers:
            for cluster in carrier.clusters:
                for m_idx, mblock in enumerate((cluster.m0block, cluster.m1block)):
                    if not isinstance(mblock, MIntBlock):
                        continue
                    for lane in range(0, 8):
                        cluster.add_constant(lane + m_idx * 8, -1.0, lane + m_idx * 8)

        async with asyncio.timeout(10):
            await controller.set_computer(computer)

        run = Run(config=RunConfig(op_time=100000))
        async with asyncio.timeout(10):
            await controller.start_and_await_run(run)

        for carrier in computer.carriers:
            for cluster in carrier.clusters:
                for m_idx, mblock in enumerate((cluster.m0block, cluster.m1block)):
                    if not isinstance(mblock, MIntBlock):
                        continue
                    for element in mblock.elements:
                        value = run.final_values[element.path]
                        if abs(abs(value) - 1.00) > 0.02:
                            print(value)
                        assert abs(value) == pytest.approx(
                            1.00, 0.02
                        ), "Integration did not reach expected absolute value of 1.00±0.01."
                        assert value, "Integration of positive input did not result in a positive output."

    @pytest.mark.parametrize(
        "in_a,in_b,expected",
        [
            (-1.0, 1.0, -1.0),
            (1.0, -1.0, -1.0),
            (-1.0, -1.0, 1.0),
            (1.0, 1.0, 1.0),
        ],
    )
    async def test_multiplication(self, controller: Controller, in_a, in_b, expected):
        computer = controller.computer
        for carrier in computer.carriers:
            for cluster in carrier.clusters:
                for m_idx, mblock in enumerate((cluster.m0block, cluster.m1block)):
                    if not isinstance(mblock, MMulBlock):
                        continue
                    for lane, value in zip(range(0, 8), cycle((in_a, in_b))):
                        cluster.add_constant(lane + m_idx * 8, value, lane + m_idx * 8)

        async with asyncio.timeout(10):
            await controller.set_computer(computer)

        run = Run()
        async with asyncio.timeout(10):
            await controller.start_and_await_run(run)

        for carrier in computer.carriers:
            for cluster in carrier.clusters:
                for m_idx, mblock in enumerate((cluster.m0block, cluster.m1block)):
                    if not isinstance(mblock, MMulBlock):
                        continue
                    for element in mblock.elements:
                        assert abs(run.final_values[element.path]) == pytest.approx(
                            abs(expected), 0.05
                        ), "Multiplication did not result in expected absolute value."
                        assert sign(run.final_values[element.path]) == sign(
                            expected
                        ), "Multiplication did not result in the expected sign."

    @pytest.mark.parametrize(
        "in_,expected",
        [
            (-1.0, -1.0),
            (1.0, 1.0),
            (0.3, 0.3),
        ],
    )
    async def test_id_paths(self, controller: Controller, in_, expected):
        computer = controller.computer
        for carrier in computer.carriers:
            for cluster in carrier.clusters:
                for m_idx, mblock in enumerate((cluster.m0block, cluster.m1block)):
                    if not isinstance(mblock, MMulBlock):
                        continue
                    for lane in range(0, 4):
                        cluster.add_constant(lane + m_idx * 8, -in_, lane + m_idx * 8)

        async with asyncio.timeout(10):
            await controller.set_computer(computer)

        run = Run()
        async with asyncio.timeout(10):
            await controller.start_and_await_run(run)

        for carrier in computer.carriers:
            for cluster in carrier.clusters:
                for m_idx, mblock in enumerate((cluster.m0block, cluster.m1block)):
                    if not isinstance(mblock, MMulBlock):
                        continue
                    # TODO: Include ID elements in block definition, since they will change for future MDR block
                    for path in [mblock.path / "4", mblock.path / "5", mblock.path / "6", mblock.path / "7"]:
                        assert abs(run.final_values[path]) == pytest.approx(
                            abs(expected), 0.05
                        ), "ID path did not result in expected absolute value."
                        assert sign(run.final_values[path]) == sign(
                            expected
                        ), "ID path did not result in the expected sign."

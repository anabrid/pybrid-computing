# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

from dataclasses import dataclass, field

import pytest
import typing

from pybrid.base.utils.descriptors import Validator


class IntRangeValidator(Validator):
    def __init__(self, min_: int, max_: int):
        min_ = int(min_)
        max_ = int(max_)
        if not max_ >= min_:
            (min_, max_) = (max_, min_)
        self.min = min_
        self.max = max_

    def set_default(self, instance, name, owner):
        setattr(instance, name, int((self.max - self.min) / 2))

    def parse(self, instance, value):
        return int(value)

    def validate(self, instance, value):
        if not self.min <= value <= self.max:
            raise ValueError("Value %s is not in range [%s, %s]." % (value, self.min, self.max))


def do_int_range_validator(min_: int, max_: int, value: typing.Any):
    @dataclass
    class TestClass:
        attribute: int = field(default=IntRangeValidator(min_, max_))

    instance = TestClass()
    instance.attribute = value
    assert instance.attribute == value


@pytest.mark.parametrize("min_,max_,value", [
    pytest.param(0, 10, 10),
    pytest.param(0, 10, 0),
    pytest.param(0, 10, 3),
    pytest.param(10, 0, 3),
    pytest.param(-170, -30, -30),
    pytest.param(-170, -30, -170),
    pytest.param(-170, -30, -42),
])
def test_int_range_validator(min_: int, max_: int, value: typing.Any):
    do_int_range_validator(min_, max_, value)


@pytest.mark.parametrize("min_,max_,value", [
    pytest.param(0, 10, 11),
    pytest.param(0, 10, -20),
])
def test_int_range_validator_invalid(min_: int, max_: int, value: typing.Any):
    with pytest.raises(ValueError):
        do_int_range_validator(min_, max_, value)

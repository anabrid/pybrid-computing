# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

from dataclasses import dataclass, field

from pybrid.base.utils.descriptors import Validator


@dataclass(kw_only=True)
class BaseComputation:
    pass


class ScalarMultiplicationFactor(Validator):
    def __init__(self, min, max, default):
        self._min = min
        self._max = max
        self._default = default

    def set_default(self, instance, name, owner):
        setattr(instance, name, self._default)

    def parse(self, instance, value):
        return float(value)

    def validate(self, instance, value):
        if not self._min <= value <= self._max:
            raise ValueError("Value must be between %s and %s, not %s." % (self._min, self._max, value))


@dataclass(kw_only=True)
class ScalarMultiplication(BaseComputation):
    """A scalar multiplication computing :math:`α \\cdot x(t)` for input :math:`x(t)` and fixed factor :math:`α`."""
    #: Scalar factor.
    factor: float = field(default=ScalarMultiplicationFactor(min=-1.0, max=+1.0, default=1.0))


@dataclass(kw_only=True)
class Integration(BaseComputation):
    """An integration computing :math:`k \\cdot \\int_0^t x(t) \\mathrm{d}t + ic` for input :math:`x(t)`."""
    # Inherent initial value is not supported for all integrators (Model-1 only has an IC input)
    pass


@dataclass(kw_only=True)
class Multiplication(BaseComputation):
    """A multiplication computing :math:`x(t) \\cdot y(t)` for inputs :math:`x(t)` and :math:`y(t)`."""
    pass


@dataclass(kw_only=True)
class Summation(BaseComputation):
    pass

# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

from dataclasses import dataclass, field

from pybrid.base.analog import Integration as BaseIntegration
from pybrid.base.analog import Multiplication  # noqa
from pybrid.base.analog import (
    ScalarMultiplication as BaseScalarMultiplication,
    ScalarMultiplicationFactor,
)


@dataclass(kw_only=True)
class Integration(BaseIntegration):
    #: Initial value. Must be in range [-1.0, 1.0].
    ic: float = 0.0
    #: Time constant in :math:`\frac{1}{\mathrm{s}}`. Must be one of {100, 10000}.
    k: int = 10_000

    # Inherit __doc__
    __doc__ = BaseIntegration.__doc__

    def reset(self):
        self.ic = 0.0
        self.k = 10_000


@dataclass(kw_only=True)
class ScalarMultiplication(BaseScalarMultiplication):
    #: Scalar factor α. Must be in range [-20.0, 20.0].
    factor: float = field(default=ScalarMultiplicationFactor(min=-1.0, max=+1.0, default=1.0))

    # Inherit __doc__
    __doc__ = BaseScalarMultiplication.__doc__

    def reset(self):
        self.factor = 1.0
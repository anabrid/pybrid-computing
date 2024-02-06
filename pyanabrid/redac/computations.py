# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

from dataclasses import dataclass, field

from pyanabrid.base.analog.computations import Integration as BaseIntegration
from pyanabrid.base.analog.computations import ScalarMultiplication as BaseScalarMultiplication, \
    ScalarMultiplicationFactor
from pyanabrid.base.analog.computations import Multiplication  # noqa


@dataclass(kw_only=True)
class Integration(BaseIntegration):
    #: Initial value. Must be in range [-1.0, 1.0].
    ic: float = 0.0
    #: Time constant in :math:`\frac{1}{\mathrm{s}}`. Must be one of {100, 10000}.
    k: int = 10_000

    # Inherit __doc__
    __doc__ = BaseIntegration.__doc__


@dataclass(kw_only=True)
class ScalarMultiplication(BaseScalarMultiplication):
    #: Scalar factor α. Must be in range [-20.0, 20.0].
    factor: float = field(default=ScalarMultiplicationFactor(min=-20.0, max=+20.0, default=1.0))

    # Inherit __doc__
    __doc__ = BaseScalarMultiplication.__doc__

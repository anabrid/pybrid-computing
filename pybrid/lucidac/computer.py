# Copyright (c) 2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

from pybrid.redac.computer import REDAC

class LUCIDAC(REDAC):
    """
    This is the LUCIDAC class that carries the Hybrid Controller as well as the configurations for the Lucidac.
    The :method: run() is used to initiate connection to the device and start a run with the configured circuit.

    Mostly, the difference between a REDAC and a LUCIDAC is that the LUCIDAC is not virtualized to
    use virtual entity IDs such as '00-00-00-00-00-00' but physical MACs such as '04-E9-E5-15-87-A0' - and of
    course that there is just one carrier and one cluster on that carrier.

    Consequently, the REDAC protocol can be simplified dramatically by removing, e.g., SYNCs. In its essence,
    the LUCIDAC is its own proxy
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    @property
    def name(self) -> str:
        return "LUCIDAC"

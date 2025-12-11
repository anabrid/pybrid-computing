# Copyright (c) 2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later
from typing import List, Optional

import pybrid.base.proto.main_pb2 as pb
from pybrid.redac.entities import Entity, Path
from pybrid.redac.computer import REDAC
from pybrid.lucidac.front_panel import FrontPanel
from pybrid.lucidac.protocol.serializer import LUCIDACSerializer, LUCIDACDeserializer

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

    #: models the (crrently) LUCIDAC-exclusive front panel with signal generators and LEDs
    front_panel: FrontPanel = FrontPanel(Path(("00-00-00-00-00-00", "FP")))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    @property
    def name(self) -> str:
        return "LUCIDAC"
    
    def get_config_entities(self) -> List[Entity]:
        """
        See :func:`AnalogComputer.get_config_entities`.
        """
        return [*self.entities, self.front_panel]
    
    def global_entities(self) -> List[Entity]:
        """
        See :func:`AnalogComputer.global_entities`.
        """
        return [self.front_panel]

    def get_serializer_implementation(self) -> type:
        """
        See :func:`AnalogComputer.get_serializer_implementation`.
        """
        return LUCIDACSerializer
    
    def get_deserializer_implementation(self) -> type:
        """
        See :func:`AnalogComputer.get_deserializer_implementation`.
        """
        return LUCIDACDeserializer
    
    
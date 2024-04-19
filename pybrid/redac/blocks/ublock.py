# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

from dataclasses import field, dataclass
from itertools import chain

from .block import SwitchingBlock, SignalConnectionError
from ..entities import EntityClass, EntityType


@EntityType.register(EntityClass.UBLOCK, None, None, None)
@dataclass
class UBlock(SwitchingBlock):
    """
    A voltage fork block (U-Block) in a REDAC.
    It can distribute each of the 16 input signals to one of the 32 output signals.
    """
    #: List of inputs forked to each of the outputs.
    #: Each element in the list corresponds to one output.
    #: The outputs are set to the input index specified by the respective array element.
    #: Use None (null in JSON) to disable an output.
    #: The firmware may accept additional JSON structures (see JSON schema).
    outputs: list[int | None] = field(default_factory=lambda: [None] * 32)
    #: List of alternate signals to activate.
    #: The U-Block implements a set of alternate signals, e.g. the 1-reference and cluster input signals.
    #: Each signal is identified by a unique number and if present in the list, is activated.
    #: The signals are: 0-7 denote cluster input signals 0-7, 8 denotes the 1-reference.
    #: Currently, there is no way to disable an alternate signal.
    alt_signals: list[int] = field(default_factory=list)

    def apply_partial_configuration(self, attribute, value):
        if attribute == "alt_signals":
            self.alt_signals = list(map(int, value.split(',')))
        else:
            raise AttributeError("Can not apply configuration to attribute %s like this." % attribute)

    def connect(self, input, output, *outputs, force=False):
        # Sanity check before actually doing anything
        if not force:
            for out in chain([output], outputs):
                if self.outputs[out] is not None:
                    raise SignalConnectionError(
                        "Output %s is already in use. Use the force argument to overwrite." % out)
        # Actually connect
        for out in chain([output], outputs):
            self.outputs[out] = input

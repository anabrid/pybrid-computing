# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

from dataclasses import dataclass, field

from .block import SwitchingBlock, SignalConnectionError
from ..entities import EntityClass, EntityType


@EntityType.register(EntityClass.IBLOCK, None, None, None)
@dataclass
class IBlock(SwitchingBlock):
    """
    A current summation block (I-Block) in a REDAC.
    It can connect and sum up a subset of the 32 inputs to each of the 16 outputs.
    """

    #: List of inputs connected to each output.
    #: Each sub-list in the list corresponds to one output.
    #: The outputs are set to the sum of the inputs specified by the sub-list in the respective array element.
    #: Use an empty sub-list to disable an output.
    #: The firmware may accept additional JSON structures (see JSON schema).
    outputs: list[set[int]] = field(default_factory=lambda: [set()] * 16)

    def connect(self, *connections, force=False):
        *input_idxs, output_idx = connections
        input_idxs = set(input_idxs)
        # Check if input is already connected to another output (signal-splitting is usually wrong)
        if not force:
            for other_output_idx, other_output in enumerate(self.outputs):
                if other_output_idx == output_idx:
                    continue
                if other_output is not None and other_output.intersection(input_idxs):
                    raise SignalConnectionError(
                        "One of inputs %s is already connected to output %s. Use the force argument to ignore." % (
                            input_idxs, other_output_idx))
        self.outputs[output_idx] = self.outputs[output_idx].union(input_idxs)

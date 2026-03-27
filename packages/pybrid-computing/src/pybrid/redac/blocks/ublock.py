# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

from dataclasses import field, dataclass
from itertools import chain

from pybrid.redac.blocks.block import SwitchingBlock, SignalConnectionError
from pybrid.redac.entities import EntityClass, EntityType


@EntityType.register(EntityClass.UBLOCK)
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
    constant: float | bool = False

    def apply_partial_configuration(self, attribute, value):
        raise AttributeError("Can not apply configuration to attribute %s like this." % attribute)

    def set_constant(self, value: bool | float):
        """
        Enable or disable the constant value on B-group inputs (i.e. IN15 on first chip, IN14 on second chip),
        allowing you to inject a constant by connecting input 14 to outputs 16-31 or input 15 to outputs 0-15.

        Consider using Cluster.add_constant instead.

        `value` must be -1.0, -0.1, 0, +0.1 or +1.0 and corresponds to the magnitude and sign of the constant.
        `false` or zero disables the constant input such that the original analog inputs are available.
        `true` is equivalent to +1.0.
        """
        self.constant = value

    def connect(self, input, output, *outputs, force=False):
        # Sanity check before actually doing anything
        if not force:
            for out in chain([output], outputs):
                if self.outputs[out] is not None and self.outputs[out] != input:
                    raise SignalConnectionError(
                        "Output %s is already in use. Use the force argument to overwrite." % out
                    )
        # Actually connect
        for out in chain([output], outputs):
            self.outputs[out] = input

    def reset(self):
        self.outputs = [None] * 32
        self.constant = False
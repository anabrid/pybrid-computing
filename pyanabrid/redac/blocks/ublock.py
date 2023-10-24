# Copyright (c) 2022 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
#
# This file is part of the pyanabrid software packet.
#
# ANABRID_BEGIN_LICENSE:GPL
# Commercial License Usage
# Licensees holding valid commercial anabrid licenses may use this file in
# accordance with the commercial license agreement provided with the
# Software or, alternatively, in accordance with the terms contained in
# a written agreement between you and Anabrid GmbH. For licensing terms
# and conditions see https://www.anabrid.com/licensing. For further
# information use the contact form at https://www.anabrid.com/contact.
#
# GNU General Public License Usage
# Alternatively, this file may be used under the terms of the GNU
# General Public License version 3 as published by the Free Software
# Foundation and appearing in the file LICENSE.GPL3 included in the
# packaging of this file. Please review the following information to
# ensure the GNU General Public License version 3 requirements
# will be met: https://www.gnu.org/licenses/gpl-3.0.html.
# For Germany, additional rules exist. Please consult /LICENSE.DE
# for further agreements.
# ANABRID_END_LICENSE

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

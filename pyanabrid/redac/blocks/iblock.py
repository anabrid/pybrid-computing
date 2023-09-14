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

from dataclasses import dataclass, field

from .block import SwitchingBlock, SignalConnectionError
from ..entities import EntityClass, EntityType


@EntityType.register(EntityClass.IBLOCK, None, None, None)
@dataclass
class IBlock(SwitchingBlock):
    """
    A current summation block (I-Block) in a REDAC.
    """
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

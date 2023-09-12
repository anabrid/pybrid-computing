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

from pyanabrid.base.hybrid.elements import ComputationElement as BaseComputationElement


class ComputationElement(BaseComputationElement):
    @classmethod
    def generate_partial_configuration(cls, attribute, value):
        if field := cls.computation_class.__dataclass_fields__.get(attribute, None):
            return {attribute: field.type(value)}
        else:
            raise ValueError("Unknown attribute %s for %s." % (attribute, cls))

    def apply_partial_configuration(self, attribute, value):
        if field := self.computation_class.__dataclass_fields__.get(attribute, None):
            setattr(self.computation, attribute, field.type(value))
        else:
            raise ValueError("Unknown attribute %s for %s." % (attribute, self.__class__))

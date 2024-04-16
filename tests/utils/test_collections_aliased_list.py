# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

from pyanabrid.base.utils.collections import AliasedList


def test_collections_aliased_list():
    al = AliasedList([1, 2, 3])
    al.add_alias("zwei", 1)  # 1 is idx

    assert al["zwei"] == 2

    # Alias to alias
    al.add_alias("nochmalzwei", "zwei")
    assert al._aliases["nochmalzwei"] == 1
    assert al["nochmalzwei"] == 2

    # But alias to alias does not change when changing alias
    al.add_alias("zwei", 0)
    assert al["zwei"] == 1
    assert al["nochmalzwei"] != al["zwei"]

    # Slices are handled without aliases
    assert al[0:2] == [1, 2]

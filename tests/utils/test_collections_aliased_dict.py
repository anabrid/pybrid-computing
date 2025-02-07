# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

from pybrid.base.utils.collections import AliasedDict


def test_aliased_dict():
    ad = AliasedDict()
    assert not ad

    ad["set_item"] = True
    assert ad["set_item"]

    ad.update({"an_answer": 42})
    assert ad
    assert ad["an_answer"] == 42

    ad.add_alias("yet_again", "an_answer")
    assert ad["yet_again"] is ad["an_answer"]

# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import typing


class _AliasMixin:
    # Based on jasonharper's suggestion from https://stackoverflow.com/a/46406510
    _aliases: typing.Dict

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._aliases = dict()

    def __getitem__(self, item):
        return super().__getitem__(self._aliases.get(item, item))

    def __setitem__(self, key, value):
        return super().__setitem__(self._aliases.get(key, key), value)

    def add_alias(self, alias, key):
        # Allow aliases to aliases, but only in the sense that they are resolved here
        resolved_key = self._aliases.get(key, key)
        self._aliases[alias] = resolved_key


class AliasedDict(_AliasMixin, dict):
    pass


class AliasedList(_AliasMixin, list):
    def __getitem__(self, item):
        if isinstance(item, slice):
            return list.__getitem__(self, item)
        else:
            return super().__getitem__(item)

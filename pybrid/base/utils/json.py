# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later


from json import JSONEncoder as BuiltinJSONEncoder


class JSONEncoder(BuiltinJSONEncoder):
    def default(self, o):
        if custom_to_dict := getattr(o, "dict", None):
            if callable(custom_to_dict):
                return custom_to_dict()
            else:
                return custom_to_dict
        else:
            return super().default(o)

# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later


class Validator:

    def __set_name__(self, owner, name):
        self._name = '_' + name

    def __get__(self, instance, owner=None):
        if instance is None:
            # Return the validator itself when accessed from class level
            # This allows Pydantic v2 to introspect the field without raising an error
            return self
        if not hasattr(instance, self._name):
            self.set_default(instance, self._name, owner)
        return getattr(instance, self._name)

    def __set__(self, instance, value):
        # There seems to be a bug in dataclass.field, see https://stackoverflow.com/a/76092152.
        if isinstance(value, type(self)):
            return
        value_ = self.parse(instance, value)
        self.validate(instance, value_)
        setattr(instance, self._name, value_)

    def set_default(self, instance, name, owner):
        ...

    def parse(self, instance, value):
        return value

    def validate(self, instance, value):
        pass

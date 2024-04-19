# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later


class ManagedAsyncResource:
    def __init__(self, obj, on_enter='_init', on_exit='_deinit'):
        self.obj = obj
        self.on_enter = on_enter
        self.on_exit = on_exit

    async def _call(self, key):
        if key is None:
            return

        if isinstance(key, str):
            attr_ = getattr(self.obj, key)
            if callable(attr_):
                return await attr_()
            else:
                raise NotImplementedError
        raise NotImplementedError

    async def __aenter__(self):
        await self._call(self.on_enter)
        return self.obj

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self._call(self.on_exit)

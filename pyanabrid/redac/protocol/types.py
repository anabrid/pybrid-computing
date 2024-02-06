# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import typing

from pydantic import BaseModel


class SuccessInfo(BaseModel):
    """
    Data type used in responses indicating whether the associated request was successful.
    """
    #: :code:`True` if response was successful, :code:`False` otherwise.
    success: bool
    #: An optional error message. Always None if success is :code:`True`.
    error: typing.Optional[str]

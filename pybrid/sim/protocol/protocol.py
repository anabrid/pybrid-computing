# Copyright (c) 2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import logging

from ..config import SimConfig
from ...redac.protocol.protocol import Protocol as REDACProtocol
from .messages import SetSimRequest, SetSimResponse

logger = logging.getLogger(__name__)

class Protocol(REDACProtocol):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    async def set_sim(self, sim_config: SimConfig):
        response = await self.send_message_and_wait_response(SetSimRequest(config=sim_config))
  
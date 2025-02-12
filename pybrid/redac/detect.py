# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import asyncio
import logging
from ipaddress import ip_address, ip_network

from zeroconf import IPVersion, Zeroconf, ServiceStateChange
from zeroconf.asyncio import AsyncZeroconf, AsyncServiceBrowser, AsyncServiceInfo

logger = logging.getLogger(__name__)


class ZeroconfDetector:
    """
    Helper class to detect available carrier boards with zeroconf/mDNS.
    """

    azc: AsyncZeroconf
    async_browser: AsyncServiceBrowser
    services: dict[str, AsyncServiceInfo]
    _PENDING_TASKS: set[asyncio.Task]

    SERVICE_TYPES = [
        "_lucijsonl._tcp.local.",
    ]
    DEFAULT_TIMEOUT = 3

    def __init__(self):
        self.azc = AsyncZeroconf(ip_version=IPVersion.V4Only)
        self.async_browser = AsyncServiceBrowser(
            self.azc.zeroconf, self.SERVICE_TYPES, handlers=[self._on_service_state_change]
        )
        self.services = dict()
        self._PENDING_TASKS = set()

    @property
    def devices(self) -> list[tuple]:
        return [self.service_info_to_device(service) for service in self.services.values()]

    async def __aenter__(self):
        await self.azc.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.azc.__aexit__(exc_type, exc_val, exc_tb)
        await asyncio.wait_for(asyncio.gather(*self._PENDING_TASKS, return_exceptions=True), self.DEFAULT_TIMEOUT)

    def _on_service_state_change(
        self, zeroconf: Zeroconf, service_type: str, name: str, state_change: ServiceStateChange
    ):
        logger.debug("Zeroconf service %s state changed: %s", name, state_change)
        # Pass onto an actual async function to use get_service_info
        task = asyncio.ensure_future(self._async_on_service_state_change(zeroconf, service_type, name, state_change))
        self._PENDING_TASKS.add(task)
        task.add_done_callback(self._PENDING_TASKS.discard)

    async def _async_on_service_state_change(
        self, zeroconf: Zeroconf, service_type: str, name: str, state_change: ServiceStateChange
    ):
        info = await self.azc.async_get_service_info(service_type, name, timeout=self.DEFAULT_TIMEOUT)
        if state_change in (ServiceStateChange.Added, ServiceStateChange.Updated):
            self.services[name] = info
        else:
            self.services.pop(name, None)

    @staticmethod
    def service_info_to_device(service_info: AsyncServiceInfo) -> tuple:
        # TODO: Figure out when one would get multiple addresses.
        host = service_info.parsed_addresses(IPVersion.V4Only)[0]
        return host, service_info.port, service_info.name

    async def await_at_least_one_service(self):
        while not self.services:
            await asyncio.sleep(0.1)
        return self.services


async def detect_in_network(network: ip_network) -> list[tuple]:
    async with ZeroconfDetector() as detector:
        # We need at least one host
        try:
            await asyncio.wait_for(detector.await_at_least_one_service(), 2)
        except asyncio.TimeoutError as exc:
            raise asyncio.TimeoutError("No available network devices found.") from exc
        # But give a bit more time for additional ones to be registered
        await asyncio.sleep(4.2)
        # Only use devices in selected network
        devices = list(filter(lambda host_port: ip_address(host_port[0]) in network, detector.devices))
        if not devices:
            raise RuntimeError(f"No available network devices in {network}.")
    return devices


if __name__ == "__main__":

    async def _main():
        print("Detecting network devices...")
        print(await detect_in_network(ip_network("0.0.0.0/0")))

    asyncio.run(_main())

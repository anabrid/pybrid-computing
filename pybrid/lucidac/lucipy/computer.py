# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import asyncio
import logging
import os
import urllib.parse
import warnings
from ipaddress import ip_network

import pybrid.base.proto.main_pb2 as pb
from pybrid.base.utils.addressing import Addressing
from pybrid.lucidac.controller import Controller as LUCIDACController
from pybrid.lucidac.lucipy.circuits import *
from pybrid.redac import DAQConfig, RunConfig, Run
from pybrid.redac.detect import detect_in_network

logging.basicConfig(level=40)
formatter = logging.Formatter(fmt="{asctime} | {levelname} | {module} | {message}",
                              style="{",
                              datefmt="%Y-%m-%d %H:%M:%S")
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger = logging.getLogger(__name__)
logger.parent.handlers = []
logger.addHandler(console_handler)
logger.setLevel(level=20)

class LUCIDACWrapper:
    """
    This wrapper class should be used as a replacment to the LUCIDAC class
    """

    ENDPOINT_ENV_NAME = "LUCIDAC_ENDPOINT"
    default_port = 5732
    
    def __init__(self, endpoint: str | None = None):
        self.circuit = None
        self.daq_config = DAQConfig()
        self.run_config = RunConfig()

        if not endpoint:
            if self.ENDPOINT_ENV_NAME in os.environ:
                endpoint = os.environ[self.ENDPOINT_ENV_NAME]
            else:
                logger.warning(f"No endpoint specified using {self.ENDPOINT_ENV_NAME}, " \
                    "selecting LUCIDAC through auto-detection...")
                
                devices = asyncio.run(detect_in_network(ip_network("0.0.0.0/0")))

                if len(devices) == 0:
                    raise Exception("No LUCIDAC found, please explicitly set one with -h, -p args.")
                
                host, port, name = devices[0]
                if len(devices) > 1:
                    logger.warning(f"Multiple LUCIDACs found, using the first one ({name}) - use options -h and -p to select a specific LUCIDAC.")

                endpoint = f"tcp://{host}:{port}"

        self.url = urllib.parse.urlparse(endpoint)

        # Host or device name. Note that hostnames are transfered to lowercase while pathnames will not.
        self.host = (self.url.hostname or "") + (self.url.path or "")

        # TCP/IP Port as integer. If not given, defaults to default TCP port.
        self.port = int(self.url.port or self.default_port)
    
    def set_log_level(self, level):
        # Sets the level of the lucipy logger.
        logger.setLevel(level)

    def set_circuit(self, circuit: Circuit):
        _, self.circuit = circuit.to_config()
    
    def set_run(self, **kwargs):
        self.run_config = RunConfig(**kwargs)
    
    def set_daq(self, **kwargs):
        self.daq_config = DAQConfig(**kwargs)
    
    def run(self, **kwargs) -> Union[type[Run],type[list[Run]]]:
        asyncio.run(self._run(**kwargs))
        if hasattr(self, "executable_runs"):
            return self.executable_runs
        else:
            return self.executable_run

    async def _run(self, **kwargs):
        # Method to connect to, set configurations on and initiate run on physical Lucidac.
        # This is the first method to actually communicate with the Lucidac through the socket.

        logger.info(f"Start LUCIDAC at {self.host}:{self.port}.")
        controller = LUCIDACController(standalone=True)
        await controller.add_device(self.host, self.port)

        try:
            await controller.reset()

            logger.debug("Creating executable run class...")
            run_class = controller.get_run_implementation()

            if self.circuit is None:
                raise Exception("No circuit set for execution!")
            
            # LUCIDAC uses physical MACs, need to map virtual (portable)
            # addresses here to physical device
            circuit = Addressing.virtual_to_physical(controller.computer, self.circuit)

            logger.info("Setting controller configuration by circuit...")
            await controller.forward_set_config(pb.ConfigCommand(bundle=circuit.bundle))

            logger.info("Executing run...")
            self.executable_run = await controller.start_and_await_run(
                run_class(config=self.run_config, daq=self.daq_config))
            logger.info("Run done...")
        finally:
            await controller.stop()

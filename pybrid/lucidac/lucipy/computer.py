# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import logging, os, urllib.parse, asyncio
from pybrid.redac import DAQConfig, RunConfig, Run

from pybrid.lucidac.lucipy.circuits import *
from pybrid.lucidac.controller import Controller as LUCIDACController

import pybrid.base.proto.main_pb2 as pb
from pybrid.base.utils.json import JSONConfigAdapter

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
        self.daq_config = DAQConfig()
        self.run_config = RunConfig()

        if not endpoint:
            if self.ENDPOINT_ENV_NAME in os.environ:
                endpoint = os.environ[self.ENDPOINT_ENV_NAME]
            else:
                raise ValueError("No endpoint provided as argument or in ENV variable "
                                    + self.ENDPOINT_ENV_NAME + 
                                    " and did not discover an USB or network endpoint. No missing external libraries encountered.")
        self.url = urllib.parse.urlparse(endpoint)

        # Host or device name. Note that hostnames are transfered to lowercase while pathnames will not.
        self.host = (self.url.hostname or "") + (self.url.path or "")

        # TCP/IP Port as integer. If not given, defaults to default TCP port.
        self.port = int(self.url.port or self.default_port)
    
    def set_log_level(self, level):
        # Sets the level of the lucipy logger.
        logger.setLevel(level)

    def set_circuit(self, circuit: Circuit):
        # Generates the carrier configuration that corrosponds to the circuit.

        if hasattr(self, "carrier_config"):
            self.carrier_configs = [self.carrier_config]
            delattr(self, "carrier_config")
            self.carrier_configs.append(circuit.generate())
        else:
            if hasattr(self, "carrier_configs"):
                self.carrier_configs.append(circuit.generate())
            else:
                self.carrier_config = circuit.generate()
    
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
        self.controller = LUCIDACController(standalone=True)
        await self.controller.add_device(self.host, self.port)

        logger.debug("Resetting controller and LUCIDAC to its initial configuration...")
        await self.controller.reset()

        logger.debug("Creating executable run class...")
        run_class = self.controller.get_run_implementation()

        if hasattr(self, "carrier_config"):
            logger.debug("Setting controller configuration by circuit...")
            pb_config = JSONConfigAdapter.parse(
                {
                    self.controller.lucidac_entity : self.carrier_config,
                },
                self.controller.computer)
            await self.controller.forward_set_config(pb.ConfigCommand(bundle=pb.ConfigBundle(configs=pb_config)))
            
            logger.info("Executing run...")
            self.executable_run = await self.controller.start_and_await_run(run_class(config=self.run_config, daq=self.daq_config))
            logger.info("Run done...")

        elif hasattr(self, "carrier_configs"):
            self.executable_runs = []
                    
            for i, carrier_config in enumerate(self.carrier_configs):
                try:
                    logger.info(f"Circuit {i:4.0f}")
                    logger.debug("Setting controller configuration by circuit...")
                    pb_config = JSONConfigAdapter.parse(
                        {
                            self.controller.lucidac_entity : carrier_config,
                        },
                        self.controller.computer)

                    await self.controller.forward_set_config(pb.ConfigCommand(bundle=pb.ConfigBundle(configs=pb_config)))
                    
                    logger.debug("Executing run...")
                    self.executable_runs.append(
                        await self.controller.start_and_await_run(
                            run_class(config=self.run_config, daq=self.daq_config)
                        )
                    )
                    logger.debug("Run done...")

                except TimeoutError as exc:
                    print(exc)
            logger.info("All runs done.")

        else:
            logger.warning("No circuits set.")
            pass

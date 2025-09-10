#!/usr/bin/env python3

import logging, os, json, sys, urllib.parse, asyncio
from typing import Dict, Any

from pybrid.redac import Controller, DAQConfig, RunConfig, Run
from .circuits import Circuit

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

class LUCIDAC:
    """
    The LUCIDAC class that carries the Hybrid Controller as well as the configurations for the Lucidac.
    The :method: run() is used to initiate connection to the device and start a run with the configured circuit.
    """
    
    ENDPOINT_ENV_NAME = "LUCIDAC_ENDPOINT"
    default_port = 5732
    
    def __init__(self, endpoint: str | None = None):
        self.controller = Controller(standalone=True)
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
        self.carrier_config = circuit.generate()

    def set_config_from_dict(self, config: Dict[str, Any]):        
        if "00-00-00-00-00-00" in config.keys():
            self.carrier_config = config["00-00-00-00-00-00"]
        else:
            self.carrier_config = config

    def set_run(self, **kwargs):
        self.run_config = RunConfig(**kwargs)
    
    def set_daq(self, **kwargs):
        self.daq_config = DAQConfig(**kwargs)
    
    def run(self) -> type[Run]:
        asyncio.run(execute_run(self))
        return self.executable_run
    
    async def arun(self) -> type[Run]:
        await execute_run(self)
        return self.executable_run

async def execute_run(self):
    # Method to connect to, set configurations on and initiate run on physical Lucidac.
    # This is the first method to actually communicate with the Lucidac through the socket.

    logger.info(f"Initializing LUCIDAC at {self.host}:{self.port}.")
    await self.controller.add_device(self.host, self.port)

    logger.debug("Resetting controller and LUCIDAC to its initial configuration.")
    await self.controller.reset()
    
    logger.debug("Setting controller configuration by circuit.")
    for protocol, managed_paths in self.controller.protocols.items():
        for carrier in list(self.controller.computer.carriers):
            if carrier.path in managed_paths:
                configure_carrier(self.carrier_config, carrier)
                await protocol.set_config(carrier)
                print(await protocol.get_config(carrier.path))
    
    logger.debug("Creating executable Run instance.")
    run_class = self.controller.get_run_implementation()
    self.executable_run = run_class(config=self.run_config, daq=self.daq_config)

    logger.info("Executing run.")
    await self.controller.start_and_await_run(self.executable_run)
    await self.controller.reset()
    
    logger.info("Run done.")

def configure_carrier(carrier_config: dict, carrier) -> None:
    # Create a configured carrier instance from a given JSON-style carrier configuration.

    if "adc_channels" in carrier_config.keys():
        carrier.adc_channels = carrier_config["adc_channels"]
    carrier.acl_select = carrier_config.get("acl_select", 8 * ["internal"])
    carrier.clusters[0].set_constant(carrier_config["/0"]["/U"].get("constant", False))

    for (idx, value) in enumerate(carrier_config["/0"]["/C"]['elements']):
        carrier.clusters[0].cblock.elements[idx].factor = value

    for (idx, value) in enumerate(carrier_config["/0"]["/U"]["outputs"]):
        carrier.clusters[0].ublock.outputs[idx] = value

    for (idx, value) in enumerate(carrier_config["/0"]["/I"]["upscaling"]):
        carrier.clusters[0].iblock.upscaling[idx] = value

    for (idx, value) in enumerate(carrier_config["/0"]["/I"]["outputs"]):
        carrier.clusters[0].iblock.outputs[idx] = set(value)

    for (idx, elem) in enumerate(carrier_config["/0"]["/M0"]['elements']):
        carrier.clusters[0].m0block.elements[idx].ic = elem["ic"]
        carrier.clusters[0].m0block.elements[idx].k = elem["k"]
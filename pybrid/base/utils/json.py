# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import logging
import typing
from json import JSONEncoder as BuiltinJSONEncoder

import pybrid.base.proto.main_pb2 as pb
from pybrid.base.hybrid.computer import AnalogComputer

logger = logging.getLogger(__name__)

class JSONEncoder(BuiltinJSONEncoder):
    def default(self, o):
        if custom_to_dict := getattr(o, "dict", None):
            if callable(custom_to_dict):
                return custom_to_dict()
            else:
                return custom_to_dict
        else:
            return super().default(o)


class JSONConfigAdapter:
    """
    Parses JSON-based configs through a computer model and returns it as protobuf
    version.
    """

    # map to lienar carriers for virtual addresses
    _VIRTUAL_ADRESSES = [
        "00-00-00-00-00-00",
        "00-00-00-00-00-01",
        "00-00-00-00-00-02",
        "00-00-01-00-00-00",
        "00-00-01-00-00-01",
        "00-00-01-00-00-02",
        "01-00-00-00-00-00",
        "01-00-00-00-00-01",
        "01-00-00-00-00-02",
        "01-00-01-00-00-00",
        "01-00-01-00-00-01",
        "01-00-01-00-00-02"
    ]

    @classmethod
    def parse(cls, config: typing.Dict[str, typing.Any], computer: AnalogComputer, use_virtual_macs: bool = False) -> typing.List[pb.Config]:
        has_virtual_warning = False

        for carrier_id, carrier_config in config.items():

            # find carrier object in computer
            carrier = None

            if not use_virtual_macs and carrier_id in cls._VIRTUAL_ADRESSES:
                if not has_virtual_warning:
                    logger.warning(f"Detected virtual MAC address {carrier_id} in config, will heuristically map to entities...")
                    has_virtual_warning = True

                # virtual addresses that would normaly go through proxy
                carrier_index = cls._VIRTUAL_ADRESSES.index(carrier_id)
                if carrier_index < len(computer.carriers):
                    carrier = computer.carriers[carrier_index]
            else:
                for _carrier in computer.carriers:
                    if str(_carrier.path) == carrier_id:
                        carrier = _carrier
                        break

            if carrier is None:
                raise Exception(f"Carrier {carrier_id} not found!")

            for cluster_ix in range(len(carrier.clusters)):
                c_path = f"/{cluster_ix}"

                if c_path not in carrier_config:
                    continue

                carrier.adc_channels = carrier_config["adc_channels"]
                carrier.acl_select = carrier_config["acl_select"] if "acl_select" \
                    in carrier_config else 8 * ["internal"]
                carrier.clusters[cluster_ix].set_constant(carrier_config[c_path]["/U"].get("constant", False))

                for (idx, value) in enumerate(carrier_config[c_path]["/C"]['elements']):
                    carrier.clusters[cluster_ix].cblock.elements[idx].factor = value

                for (idx, value) in enumerate(carrier_config[c_path]["/U"]["outputs"]):
                    carrier.clusters[cluster_ix].ublock.outputs[idx] = value

                for (idx, value) in enumerate(carrier_config[c_path]["/I"]["upscaling"]):
                    carrier.clusters[cluster_ix].iblock.upscaling[idx] = value

                for (idx, value) in enumerate(carrier_config[c_path]["/I"]["outputs"]):
                    carrier.clusters[cluster_ix].iblock.outputs[idx] = set(value)

                for (idx, elem) in enumerate(carrier_config[c_path]["/M0"]['elements']):
                    carrier.clusters[cluster_ix].m0block.elements[idx].ic = elem["ic"]
                    carrier.clusters[cluster_ix].m0block.elements[idx].k = elem["k"]

            if "/FP" in carrier_config:
                from pybrid.redac.entities import Path
                from pybrid.lucidac.front_panel import FrontPanel, SignalGenerator

                fp_config = carrier_config["/FP"]
                computer.front_panel.leds=fp_config["leds"]
                computer.front_panel.signal_generator=SignalGenerator(
                    frequency=fp_config["frequency"],
                    phase=fp_config["phase"],
                    wave_form=fp_config["wave_form"],
                    amplitude=fp_config["amplitude"],
                    square_voltage_low=fp_config["square_voltage_low"],
                    square_voltage_high=fp_config["square_voltage_high"],
                    offset=fp_config["offset"],
                    sleep=fp_config["sleep"],
                    dac_outputs=fp_config["dac_outputs"]
                )

        return computer.to_pb()
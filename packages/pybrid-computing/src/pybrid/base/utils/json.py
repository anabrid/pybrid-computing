# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import logging
import typing
from json import JSONEncoder as BuiltinJSONEncoder

import pybrid.base.proto.main_pb2 as pb
from pybrid.redac.computer import REDAC
from pybrid.base.proto.io import ProtoVersioning

from pybrid.redac.carrier import ADCChannel, Carrier

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


class LegacyConfigJSONParser:

    @classmethod
    def extract_carrier(cls, computer: REDAC, carrier_id: str) -> Carrier:
        for entity in computer.entities:
            mac = entity.path.to_mac()

            if mac == carrier_id:
                return entity
            
        raise Exception(f"Unable to find carrier {carrier_id} in computer")


    @classmethod
    def parse(cls, config: typing.Dict[str, typing.Any], computer: REDAC) -> pb.File:
        """
        Parses a legacy-style, nested config and exports it in protobuf format.

        Args:
            config: Nested dictionary containing a config keyed by carrier MAC.
            computer: The computer object used as target to map the config.

        Returns:
            A configuration in protobuf format.
        """

        carrier_mapping = {}
        for carrier_id in config:
            carrier_mapping[carrier_id] = cls.extract_carrier(computer, carrier_id)

        for carrier_id, carrier_config in config.items():
            carrier = carrier_mapping[carrier_id]

            if carrier is None:
                raise Exception(f"Carrier {carrier_id} not found!")

            for cluster_ix in range(len(carrier.clusters)):
                c_path = f"/{cluster_ix}"

                if c_path not in carrier_config:
                    continue
                    
                carrier.adc_config = [ADCChannel(index=idx) for idx in \
                    carrier_config["adc_channels"] if idx is not None] if \
                    "adc_channels" in carrier_config else []
                carrier.clusters[cluster_ix].set_constant(carrier_config[c_path]["/U"].get("constant", False))
                carrier.acl_select = carrier_config["acl_select"] if "acl_select" \
                    in carrier_config else 8 * ["internal"]

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
                from pybrid.lucidac.front_plane import FrontPlane, SignalGenerator

                fp_config = carrier_config["/FP"]
                carrier.front_plane.leds=fp_config["leds"]
                carrier.front_plane.signal_generator=SignalGenerator(
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

        # serialize configuration (with Carrier addresses)
        serializer = computer.get_serializer()()
        module = serializer.serialize(computer)

        return pb.File(
            version=ProtoVersioning.current(),
            module=module,
        )
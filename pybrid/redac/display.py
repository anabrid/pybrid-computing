# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

from .computer import REDAC


class TreeDisplay:

    @staticmethod
    def render(redac: REDAC):
        buffer = ""
        buffer += "Analog Computer\n"

        # TODO: Do it better :)
        for carrier in redac.carriers:
            buffer += "├── " + carrier.__class__.__name__ + " @ " + str(carrier.path) + "\n"
            for cluster in carrier.clusters:
                buffer += "│   ├── " + cluster.__class__.__name__ + " @ " + str(cluster.path) + "\n"
                for block in cluster.children:
                    buffer += "│   │   ├── " + block.__class__.__name__ + " @ " + str(block.path) + "\n"
                    for element in block.children:
                        buffer += "│   │   │   ├── " + element.__class__.__name__ + " @ " + str(element.path) + "\n"
            if carrier.tblock:
                buffer += "├── " + carrier.tblock.__class__.__name__ + " @ " + str(carrier.tblock.path) + "\n"
            if carrier.st0block:
                buffer += "├── " + carrier.st0block.__class__.__name__ + " @ " + str(carrier.st0block.path) + "\n"
            if carrier.st1block:
                buffer += "├── " + carrier.st1block.__class__.__name__ + " @ " + str(carrier.st1block.path) + "\n"

        return buffer

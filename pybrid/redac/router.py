from typing import Dict, Set

from pybrid.redac.entities import Path, Loc
from pybrid.redac.blocks import TBlock
from pybrid.redac.carrier import Carrier


class RoutingException(Exception):
    def __init__(self, message: str = ""):
        self.message = message


def wing_clock_idx(carrier: Loc) -> int:
    if carrier.stack_id() == 0:
        return carrier.wing_id()
    return 3 - carrier.wing_id()


class Router:
    carrier_t_blocks: Dict[Loc, TBlock] = {}
    wing_t_blocks: Dict[Loc, TBlock] = {}
    stack_is_long_loop: Set[Loc] = set()
    dummy = TBlock(Path(("dummy", "T")))

    def add_t_block(self, t_block: TBlock):
        loc = t_block.loc()

        if loc.is_carrier():
            self.carrier_t_blocks[loc.carrier()] = t_block
        elif loc.is_wing():
            self.wing_t_blocks[loc.wing()] = t_block

    def add_carrier(self, carrier: Carrier):
        if carrier.tblock:
            self.add_t_block(carrier.tblock)
        if carrier.st0block:
            self.add_t_block(carrier.st0block)
        if carrier.st1block:
            self.add_t_block(carrier.st1block)

    def find_wing_t_block(self, loc: Loc) -> TBlock:
        return self.wing_t_blocks.get(loc.wing(), self.dummy)

    def find_carrier_t_block(self, loc: Loc) -> TBlock:
        return self.carrier_t_blocks.get(loc.carrier(), self.dummy)

    def set_long_loop(self, loc: Loc) -> None:
        self.stack_is_long_loop.add(loc.stack())

    # route two cluster
    def route_cluster(self, output: Loc, input: Loc):
        assert output.carrier() == input.carrier()

        if output.lane_id() < 8:
            if output != input:
                raise RoutingException("First 8 lanes only to same indices routable")
            return

        output_sector_lane = output.lane_id() - 8
        input_sector_lane = input.lane_id() - 8

        if output_sector_lane != input_sector_lane:
            raise RoutingException("Connections inside carrier only allowed between same lane indices!")

        tblock = self.find_carrier_t_block(input)
        return tblock.connect(output.cluster_id() + 1, input.cluster_id() + 1, input_sector_lane)

    def wired_ring_carrier(self, lane: Loc):
        short_loop = lane.stack() not in self.stack_is_long_loop
        loop_size = 3 if short_loop else 6
        carrier_offset = 1 if lane.lane_id() < 12 else loop_size - 1
        wired_carrier = (lane.carrier_id() + carrier_offset) % loop_size
        wired_wing = (lane.wing_id() + wired_carrier // 3) % 2
        wired_carrier %= 3
        return lane.stack() / wired_wing / wired_carrier

    # route two carrier
    def route_carrier(self, output: Loc, input: Loc):
        if output.carrier_id() == input.carrier_id():
            return self.route_cluster(output, input)

        output_carrier_block = self.find_carrier_t_block(output)
        input_carrier_block = self.find_carrier_t_block(input)

        if 8 <= output.lane_id() < 16:
            wired_lane = self.wired_ring_carrier(output)

            if wired_lane != input.carrier():
                raise RoutingException("Output lanes are connected to different carrier!")

            lane_offset = 4 if output.lane_id() < 12 else -4
            wired_lane = output.lane_id() + lane_offset

            if wired_lane != input.lane_id():
                raise RoutingException(
                    "Output connections between lanes [8, 15] are hard wired to different input lanes"
                )

            output_sector_lane = output.lane_id() - 8
            input_sector_lane = input.lane_id() - 8

            output_carrier_block.connect(output.cluster_id() + 1, 0, output_sector_lane)
            input_carrier_block.connect(0, input.cluster_id() + 1, input_sector_lane)
            return

        if 16 <= output.lane_id() < 32:
            if output != input:
                raise RoutingException("Carrier connections only allowed between common lanes")

            sector_lane = input.lane_id() - 8

            output_carrier_block.connect(output.cluster_id() + 1, 0, sector_lane)
            input_carrier_block.connect(0, input.cluster_id() + 1, sector_lane)
            stack_block = self.find_wing_t_block(output)
            stack_block.connect(output.cluster_id() + 1, input.cluster_id() + 1, sector_lane)
            return

        raise RoutingException("Lane outside [0, 31]")

    # route two wings
    def route_wing(self, output: Loc, input: Loc):
        if output.wing() == input.wing() or output.lane_id() != input.lane_id():
            self.route_carrier(output, input)
            return

        if output.lane_id() not in range(16, 32):
            raise RoutingException("Stack connection lanes out of range")

        if output.lane_id() != input.lane_id():
            raise RoutingException("Can only connect mRedac's same lanes")

        output_clock_idx = wing_clock_idx(output)
        input_clock_idx = wing_clock_idx(input)

        if 16 <= output.lane_id() < 24:
            cw = (output_clock_idx + 1) % 4 == input_clock_idx
            if not cw:
                raise RoutingException("Routing clockwise loop only on output lanes [16, 23]")
        elif 24 <= output.lane_id() < 32:
            ccw = output_clock_idx == (input_clock_idx + 1) % 4
            if not ccw:
                raise RoutingException("Routing counter clockwise loop only on output lanes [24, 31]")

        sector_lane = output.lane_id() - 8

        output_carrier_block = self.find_carrier_t_block(output)
        output_carrier_block.connect(output.cluster_id() + 1, 0, sector_lane)

        input_carrier_block = self.find_carrier_t_block(input)
        input_carrier_block.connect(0, input.cluster_id() + 1, sector_lane)

        output_stack_block = self.find_wing_t_block(output)
        input_stack_block = self.find_wing_t_block(input)
        output_stack_block.connect(output.cluster_id() + 1, 0, sector_lane)
        input_stack_block.connect(0, input.cluster_id() + 1, sector_lane)
        return

    def route(self, output: Loc, input: Loc):
        assert output.stack_id() < 2 and input.stack_id() < 2
        assert output.wing_id() < 2 and input.wing_id() < 2
        assert output.carrier_id() < 3 and input.carrier_id() < 3
        assert output.cluster_id() < 3 and input.cluster_id() < 3
        assert input.lane_id() < 32 and output.lane_id() < 32
        self.route_wing(output, input)

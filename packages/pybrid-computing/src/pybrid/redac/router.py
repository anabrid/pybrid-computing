import typing
from typing import Dict, Set, List

from pybrid.redac.blocks import TBlock
from pybrid.redac.blocks.backplane_tblock import BackplaneTBlock
from pybrid.redac.carrier import Carrier
from pybrid.redac.entities import Path, Loc


class RoutingException(Exception):
    def __init__(self, message: str = ""):
        self.message = message

class Routing:
    carrier_t_blocks: Dict[Loc, TBlock] = {}
    bpl_t_blocks: Dict[Loc, Dict[int, BackplaneTBlock]] = {}
    dummy = TBlock(Path(("dummy", "T")))
    bpl_dummy = BackplaneTBlock(Path(("dummy", "T")))

    def add_t_block(self, t_block: TBlock):
        loc = t_block.loc()
        if loc.is_carrier():
            self.carrier_t_blocks[loc.carrier()] = t_block

    def add_t_bpl_block(self, idx: int, t_block: BackplaneTBlock):
        loc = t_block.loc()
        self.bpl_t_blocks.setdefault(loc.stack(), {})[idx] = t_block

    def add_carrier(self, carrier: Carrier):
        if carrier.tblock:
            self.add_t_block(carrier.tblock)
        if carrier.st0block:
            self.add_t_bpl_block(0, carrier.st0block)
        if carrier.st1block:
            self.add_t_bpl_block(1, carrier.st1block)
        if carrier.st2block:
            self.add_t_bpl_block(2, carrier.st2block)

    def find_carrier_t_block(self, loc: Loc) -> TBlock:
        return self.carrier_t_blocks.get(loc.carrier(), self.dummy)

    def find_bpl_t_block(self, loc: Loc, idx: int) -> BackplaneTBlock:
        return self.bpl_t_blocks.get(loc.stack(), {}).get(idx, self.bpl_dummy)

class Router(Routing):

    # route two cluster
    def _route_cluster(self, output: Loc, input: Loc):
        assert output.carrier() == input.carrier()

        if output.lane_id() < 8:
            if output != input:
                raise RoutingException("First 8 lanes only to same indices routable")
            return None

        output_sector_lane = output.lane_id() - 8
        input_sector_lane = input.lane_id() - 8

        if output_sector_lane != input_sector_lane:
            raise RoutingException("Connections inside cluster only allowed between same lane indices!")

        tblock = self.find_carrier_t_block(input)
        return tblock.connect(output.cluster_id() + 1, input.cluster_id() + 1, input_sector_lane)

    def _route_carrier(self, output: Loc, input: Loc):
        if output.lane_id() != input.lane_id():
            raise RoutingException("Connections between clusters only allowed between same lane indices!")

        if 0 <= output.lane_id() < 8:
            raise RoutingException("Connections between clusters only allowed between 8 to 31 lane indices!")

        t_block = self.find_carrier_t_block(input)
        t_block.connect(output.cluster_id() + 1, input.cluster_id() + 1, input.lane_id() - 8)

    def _route_stack(self, output: Loc, input: Loc):
        if output.lane_id() != input.lane_id():
            raise RoutingException("Connections between carrier only allowed between same lane indices!")

        if not (8 <= output.lane_id() < 32 ):
            raise RoutingException("Connections between carrier only allowed between 8 to 31 lane indices!")

        offset_lane_id = output.lane_id() - 8
        partition = offset_lane_id // 8

        output_t_block = self.find_carrier_t_block(output)
        input_t_block = self.find_carrier_t_block(input)

        #index 0 is connect to backplane
        #cluster 0-2 are sector 1-3
        output_t_block.connect(output.cluster_id() + 1, 0, offset_lane_id)
        input_t_block.connect(0, input.cluster_id() + 1, offset_lane_id)

        bpl_t_block = self.find_bpl_t_block(output, partition)
        bpl_t_block.connect(output.carrier_id(), input.carrier_id(), input.lane_id() % 8)


    def route(self, output: Loc, input: Loc):
        assert output.stack_id() < 2 and input.stack_id() < 2
        assert output.carrier_id() < 7 and input.carrier_id() < 7
        assert output.cluster_id() < 3 and input.cluster_id() < 3
        assert input.lane_id() < 32 and output.lane_id() < 32
        if output.cluster() == input.cluster():
            return self._route_cluster(output, input)

        if output.carrier() == input.carrier():
            return self._route_carrier(output, input)

        if output.stack() == input.stack():
            return self._route_stack(output, input)

        raise RoutingException("Connections between stacks not implemented yet!")


class Tracer(Routing):

    #loc is a lane in a cluster after a the t block searching for the coef source
    #loc here is stack / carrier / cluster_id / lane
    def find_coef(self, loc: Loc) -> typing.Optional[Loc]:

        visited = set()

        if loc.lane_id() < 8:
            return loc

        # only here we bump cluster_id because we need 0 for backplane
        loc = loc.carrier() / (loc.cluster_id() + 1) / loc.lane_id()

        while True:
            if loc.lane_id() < 8:
                return loc

            if loc in visited:
                return None
            visited.add(loc)

            carrier_t_block = self.find_carrier_t_block(loc.carrier())

            # source is either the result of coef or from bpl t block
            tblock_lane = loc.lane_id() - 8
            source = carrier_t_block.source(loc.cluster_id(), tblock_lane)
            if source is None or not (0 <= source < 4):
                return None

            if source != 0:
                return loc.carrier() / (source - 1) / loc.lane_id()

            # here source is from backpanel
            bpl_t_block = self.find_bpl_t_block(loc, tblock_lane // 8)
            prev_carrier_id = bpl_t_block.source(loc.carrier_id(), tblock_lane % 8)
            if prev_carrier_id is None:
                return None

            if 0 <= prev_carrier_id <= 6:
                # 0 because backpanel here!
                loc = loc.stack() / prev_carrier_id / 0 / loc.lane_id()
                continue
            else:
                #external
                raise RoutingException("Connections between stacks not implemented yet!")

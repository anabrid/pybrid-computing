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
    def _route_cluster(self, src: Loc, dst: Loc):
        assert src.carrier() == dst.carrier()

        if src.lane_id() < 8:
            if src != dst:
                raise RoutingException("First 8 lanes only to same indices routable")
            return None

        output_sector_lane = src.lane_id() - 8
        input_sector_lane = dst.lane_id() - 8

        if output_sector_lane != input_sector_lane:
            raise RoutingException("Connections inside cluster are only allowed between same lane indices!")

        tblock = self.find_carrier_t_block(dst)
        return tblock.connect(src.cluster_id() + 1, dst.cluster_id() + 1, input_sector_lane)

    def _route_carrier(self, src: Loc, dst: Loc):
        if src.lane_id() != dst.lane_id():
            raise RoutingException("Connections between clusters are only allowed between same lane indices!")

        if 0 <= src.lane_id() < 8:
            raise RoutingException("Connections between clusters are only allowed between 8 to 31 lane indices!")

        t_block = self.find_carrier_t_block(dst)
        t_block.connect(src.cluster_id() + 1, dst.cluster_id() + 1, dst.lane_id() - 8)

    def _route_stack(self, src: Loc, dst: Loc):
        if src.lane_id() != dst.lane_id():
            raise RoutingException("Connections between carrier are only allowed between same lane indices!")

        if not (8 <= src.lane_id() < 32):
            raise RoutingException("Connections between carrier are only allowed between 8 to 31 lane indices!")

        offset_lane_id = src.lane_id() - 8
        partition = offset_lane_id // 8

        output_t_block = self.find_carrier_t_block(src)
        input_t_block = self.find_carrier_t_block(dst)

        #sector 0 is connect to backplane
        #cluster 0-2 are sector 1-3
        output_t_block.connect(src.cluster_id() + 1, 0, offset_lane_id)
        input_t_block.connect(0, dst.cluster_id() + 1, offset_lane_id)

        mod_dst_lane = dst.lane_id() % 8
        if src.stack() != dst.stack():
            src_bpl_t_block = self.find_bpl_t_block(src, partition)
            dst_bpl_t_block = self.find_bpl_t_block(dst, partition)

            exit_sector = 7 if src.stack_id() < dst.stack_id() else 8
            entry_sector = 8 if src.stack_id() < dst.stack_id() else 7

            src_bpl_t_block.connect(src.carrier_id(), exit_sector, mod_dst_lane)
            dir = 1 if src.stack_id() < dst.stack_id() else -1
            for btw_stack_idx in range(src.stack_id() + dir, dst.stack_id(), dir):
                btw_bpl_t_block = self.find_bpl_t_block(Loc.new_stack(btw_stack_idx), partition)
                btw_bpl_t_block.connect(entry_sector, exit_sector, mod_dst_lane)

            dst_bpl_t_block.connect(entry_sector, dst.carrier_id(), mod_dst_lane)
        else:
            bpl_t_block = self.find_bpl_t_block(src, partition)
            bpl_t_block.connect(src.carrier_id(), dst.carrier_id(), mod_dst_lane)


    def route(self, src: Loc, dst: Loc):
        assert src.carrier_id() < 7 and dst.carrier_id() < 7
        assert src.cluster_id() < 3 and dst.cluster_id() < 3
        assert dst.lane_id() < 32 and src.lane_id() < 32
        if src.cluster() == dst.cluster():
            return self._route_cluster(src, dst)

        if src.carrier() == dst.carrier():
            return self._route_carrier(src, dst)

        return self._route_stack(src, dst)


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

            # here source is from backplane
            current_stack = loc.stack()
            prev_carrier_id = loc.carrier_id()

            while True:
                bpl_t_block = self.find_bpl_t_block(current_stack, tblock_lane // 8)
                prev_carrier_id = bpl_t_block.source(prev_carrier_id, tblock_lane % 8)

                if prev_carrier_id is None:
                    return None
                elif prev_carrier_id == 8:
                    current_stack = Loc.new_stack(current_stack.stack_id() - 1)
                    prev_carrier_id = 7
                elif prev_carrier_id == 7:
                    current_stack = Loc.new_stack(current_stack.stack_id() + 1)
                    prev_carrier_id = 8
                else:
                    break

            if 0 <= prev_carrier_id <= 6:
                # 0 because backpanel here!
                loc = current_stack / prev_carrier_id / 0 / loc.lane_id()
                continue
            else:
                #external
                raise RoutingException("Connections between stacks not implemented yet!")

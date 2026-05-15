"""
Lucipy helper utilities.

Standalone functions used by the :class:`Circuit` class for lane allocation,
constant output selection, and LUCIDAC construction.
"""

from typing import List, Optional

from pybrid.redac.entities import Loc


class Helpers:
    """Collection of static helper methods for Circuit internals."""

    @staticmethod
    def next_free(occupied: List[bool], criterion=None, append_to: int = None) -> Optional[int]:
        """
        Look for the first False value within a list of truth values.

        >>> Helpers.next_free([1,1,0,1,0,0])
        2

        If no more value is free in list, it can append up to a given value:

        >>> Helpers.next_free([True]*4, append_to=3)  # None, nothing free
        >>> Helpers.next_free([True]*4, append_to=6)
        4

        :param occupied: List of boolean-like values where False means available.
        :param criterion: Optional callback that receives the potential index and
            returns True if this index is acceptable.
        :param append_to: If provided, allow virtual expansion of the list up to
            this size.
        :returns: Index of first free slot, or None if nothing is available.
        """
        for idx, val in enumerate(occupied):
            if not val and (criterion(idx) if criterion else True):
                return idx
        return len(occupied) if append_to is not None and len(occupied) < append_to else None

    @staticmethod
    def constant_output_for_lane(lane: int) -> int:
        """
        Determine the constant giver M-block output for a given lane.

        :param lane: The allocated lane number (0-31)
        :returns: 15 for lanes 0-15, 14 for lanes 16-31
        """
        return 15 if lane < 16 else 14

    @staticmethod
    def create_minimal_lucidac(mac: str):
        """Create a minimal LUCIDAC with one carrier, one cluster, all blocks, and FrontPanel.

        :param mac: MAC address string for the carrier (e.g. "AA-BB-CC-DD-EE-FF").
        """
        from pybrid.lucidac.computer import LUCIStack as PybridLUCIDAC
        from pybrid.lucidac.front_plane import FrontPlane as PybridFrontPlane
        from pybrid.redac.blocks import CBlock, IBlock, MIntBlock, MMulBlock, SHBlock, UBlock
        from pybrid.redac.carrier import Carrier
        from pybrid.redac.cluster import Cluster
        from pybrid.redac.entities import Path

        carrier_path = Path.parse(mac)
        cluster_path = carrier_path / "0"

        cluster = Cluster(
            path=cluster_path,
            location=Loc.new_cluster(0, 0, 0),
            m0block=MIntBlock(path=cluster_path / "M0"),
            m1block=MMulBlock(path=cluster_path / "M1"),
            ublock=UBlock(path=cluster_path / "U"),
            cblock=CBlock(path=cluster_path / "C"),
            iblock=IBlock(path=cluster_path / "I"),
            shblock=SHBlock(cluster_path / "SH"),
        )

        carrier = Carrier(
            path=carrier_path,
            location=Loc.new_carrier(0, 0),
            clusters=[cluster],
            tblock=None,
            front_plane=PybridFrontPlane(carrier_path / "FP"),
            acl_select=8 * ["INTERNAL"],
        )

        lucidac = PybridLUCIDAC(entities=[carrier])
        return lucidac

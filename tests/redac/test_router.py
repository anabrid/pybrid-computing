# Copyright (c) 2022-2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
Router Tests
============

Tests for the REDAC router functionality, verifying signal routing
between clusters, carriers, and wings.

Test Categories
---------------
1. Cluster Routing - Tests for intra-cluster lane routing (0-7)
2. Carrier Routing - Tests for inter-cluster routing within a carrier
3. Wing Routing - Tests for inter-carrier routing within a wing
4. Stack Routing - Tests for inter-wing routing (long loops)

Key Concepts
------------
- Lanes 0-7: Cluster-local routing only
- Lanes 8-15: Can route between clusters via T-block
- Lanes 16-31: Can route between carriers/wings via ST-blocks
- Short loop: Routing within a wing (3 carriers)
- Long loop: Routing across wings in a stack (6 carriers)

Fixtures Used
-------------
- build(): Creates a Router with full stack topology for testing
"""

import pytest
from pytest import raises

from pybrid.redac import Path
from pybrid.redac.blocks import TBlock
from pybrid.redac.blocks.backplane_tblock import BackplaneTBlock
from pybrid.redac.entities import Loc
from pybrid.redac.router import Router, RoutingException


def _make_tblock(stack: int, carrier: int) -> TBlock:
    t = TBlock(Path(("dummy", "T")))
    t.location = Loc.new_carrier(stack, carrier)
    return t


def _make_bpl_tblock(stack: int) -> BackplaneTBlock:
    t = BackplaneTBlock(Path(("dummy", "ST")))
    t.location = Loc.new_stack(stack)
    return t


def build():
    """
    Create a Router with a full two-stack topology.

    Topology per stack: 6 carriers (0-5), 3 backplane T-blocks (partitions 0-2).
    """
    router = Router()

    for carrier in range(6):
        router.add_t_block(_make_tblock(0, carrier))
    router.add_t_bpl_block(0, _make_bpl_tblock(0))
    router.add_t_bpl_block(1, _make_bpl_tblock(0))
    router.add_t_bpl_block(2, _make_bpl_tblock(0))

    for carrier in range(6):
        router.add_t_block(_make_tblock(1, carrier))

    return router


def test_cluster_0_7():
    """Lanes 0-7 route only within the same cluster; mismatched lane numbers raise RoutingException."""
    router = build()

    cluster = Loc.new_cluster(0, 0, 0)
    router.route(cluster / 0, cluster / 0)
    router.route(cluster / 1, cluster / 1)
    router.route(cluster / 2, cluster / 2)
    router.route(cluster / 3, cluster / 3)
    router.route(cluster / 4, cluster / 4)
    router.route(cluster / 5, cluster / 5)
    router.route(cluster / 6, cluster / 6)
    router.route(cluster / 7, cluster / 7)

    with raises(RoutingException):
        router.route(cluster / 0, cluster / 1)

    with raises(RoutingException):
        router.route(cluster / 7, cluster / 6)


def test_carrier():
    """Lanes 8-31 route between clusters on the same carrier; mismatched lanes or out-of-range raise errors."""
    router = build()
    # stack wing carrier cluster lane
    carrier = Loc.new_carrier(0, 0)
    router.route(carrier / 0 / 8, carrier / 1 / 8)
    router.route(carrier / 0 / 31, carrier / 1 / 31)

    with raises(RoutingException):
        router.route(carrier / 0 / 8, carrier / 1 / 9)

    with raises(AssertionError):
        router.route(carrier / 0 / 32, carrier / 1 / 32)



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


# =============================================================================
# Test Fixtures
# =============================================================================


def build():
    """
    Create a Router with a full two-stack, two-wing topology.

    Topology:
    - Stack 0:
      - Wing 0: Carriers 0, 1, 2 (T-blocks + ST0)
      - Wing 1: Carriers 0, 1, 2 (T-blocks + ST1)
    - Stack 1:
      - Wing 0: Carriers 0, 1, 2
      - Wing 1: Carriers 0, 1, 2

    Returns:
        Router configured with the full topology.
    """
    router = Router()
    router.add_t_block(TBlock(Path(("00-00-00-00-00-00", "T"))))  # Stack 0 Wing 0 Carrier 0
    router.add_t_block(TBlock(Path(("00-00-00-00-00-01", "T"))))  # Stack 0 Wing 0 Carrier 1
    router.add_t_block(TBlock(Path(("00-00-00-00-00-02", "T"))))  # Stack 0 Wing 0 Carrier 2

    router.add_t_block(TBlock(Path(("00-00-01-00-00-00", "T"))))  # Stack 0 Wing 1 Carrier 0
    router.add_t_block(TBlock(Path(("00-00-01-00-00-01", "T"))))  # Stack 0 Wing 1 Carrier 1
    router.add_t_block(TBlock(Path(("00-00-01-00-00-02", "T"))))  # Stack 0 Wing 1 Carrier 2

    router.add_t_bpl_block(0, BackplaneTBlock(Path(("00-00-00-00-00-00", "ST0"))))  # Stack 0
    router.add_t_bpl_block(1, BackplaneTBlock(Path(("00-00-00-00-00-00", "ST1"))))  # Stack 0
    router.add_t_bpl_block(2, BackplaneTBlock(Path(("00-00-00-00-00-00", "ST2"))))  # Stack 0

    router.add_t_block(TBlock(Path(("01-00-00-00-00-00", "T"))))  # Stack 1 Wing 0 Carrier 0
    router.add_t_block(TBlock(Path(("01-00-00-00-00-01", "T"))))  # Stack 1 Wing 0 Carrier 1
    router.add_t_block(TBlock(Path(("01-00-00-00-00-02", "T"))))  # Stack 1 Wing 0 Carrier 2

    router.add_t_block(TBlock(Path(("01-00-01-00-00-00", "T"))))  # Stack 1 Wing 1 Carrier 0
    router.add_t_block(TBlock(Path(("01-00-01-00-00-01", "T"))))  # Stack 1 Wing 1 Carrier 1
    router.add_t_block(TBlock(Path(("01-00-01-00-00-02", "T"))))  # Stack 1 Wing 1 Carrier 2

    return router


# =============================================================================
# Cluster Routing Tests
# =============================================================================


def test_cluster_0_7():
    """
    Test routing within cluster-local lanes (0-7).

    Lanes 0-7 can only route within the same cluster and must have
    matching source and target lane numbers. Attempting to route
    these lanes to different targets should fail with RoutingException.
    """
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


# =============================================================================
# Carrier Routing Tests
# =============================================================================


def test_carrier():
    """
    Test routing between clusters on the same carrier.

    Lanes 8-31 can route between clusters via the carrier's T-block.
    The source and target lanes must match. Lane numbers outside the
    valid range (0-31) should raise AssertionError.
    """
    router = build()
    # stack wing carrier cluster lane
    carrier = Loc.new_carrier(0, 0)
    router.route(carrier / 0 / 8, carrier / 1 / 8)
    router.route(carrier / 0 / 31, carrier / 1 / 31)

    with raises(RoutingException):
        router.route(carrier / 0 / 8, carrier / 1 / 9)

    with raises(AssertionError):
        router.route(carrier / 0 / 32, carrier / 1 / 32)




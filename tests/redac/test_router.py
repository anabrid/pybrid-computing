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

    router.add_t_block(TBlock(Path(("00-00-00-00-00-00", "ST0"))))  # Stack 0 Wing 0
    router.add_t_block(TBlock(Path(("00-00-00-00-00-00", "ST1"))))  # Stack 0 Wing 1

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

    cluster = Loc.new_cluster(0, 0, 0, 0)
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
    carrier = Loc.new_carrier(0, 0, 0)
    router.route(carrier / 0 / 8, carrier / 1 / 8)
    router.route(carrier / 0 / 31, carrier / 1 / 31)

    with raises(RoutingException):
        router.route(carrier / 0 / 8, carrier / 1 / 9)

    with raises(AssertionError):
        router.route(carrier / 0 / 32, carrier / 1 / 32)


# =============================================================================
# Wing and Stack Routing Tests
# =============================================================================


def short_loop_helper(router, wing):
    """
    Helper to test short loop routing within a wing (3 carriers).

    Short loops route signals between adjacent carriers within the same wing.
    Each carrier can send to the next carrier and receive from the previous
    carrier in the loop sequence.

    Args:
        router: The Router instance to test with.
        wing: The wing Loc to test routing within.
    """
    for idx in range(0, 2):
        prev_idx = (idx + 2) % 3
        next_idx = (idx + 1) % 3

        router.route(wing / idx / 0 / 8, wing / next_idx / 1 / 12)
        router.route(wing / idx / 0 / 9, wing / next_idx / 1 / 13)
        router.route(wing / idx / 0 / 10, wing / next_idx / 1 / 14)
        router.route(wing / idx / 0 / 11, wing / next_idx / 1 / 15)

        router.route(wing / idx / 0 / 12, wing / prev_idx / 0 / 8)
        router.route(wing / idx / 0 / 13, wing / prev_idx / 0 / 9)
        router.route(wing / idx / 0 / 14, wing / prev_idx / 0 / 10)
        router.route(wing / idx / 0 / 15, wing / prev_idx / 0 / 11)

    with raises(RoutingException):
        router.route(wing / 0 / 0 / 8, wing / 2 / 1 / 12)

    with raises(RoutingException):
        router.route(wing / 0 / 0 / 12, wing / 1 / 0 / 8)


def long_loop_helper(router, stack):
    """
    Helper to test long loop routing across wings in a stack (6 carriers).

    Long loops route signals across all 6 carriers in a stack (3 carriers
    per wing, 2 wings per stack). This enables larger feedback loops that
    span the entire stack.

    Args:
        router: The Router instance to test with.
        stack: The stack Loc to test routing within.
    """
    for idx in range(0, 5):
        prev_idx = (idx + 6 - 1) % 6
        next_idx = (idx + 1) % 6

        (carrier_id, wing_id) = (idx % 3, idx // 3)
        (prev_carrier_id, prev_wing_id) = (prev_idx % 3, prev_idx // 3)
        (next_carrier_id, next_wing_id) = (next_idx % 3, next_idx // 3)

        carrier = stack / wing_id / carrier_id
        prev_carrier = stack / prev_wing_id / prev_carrier_id
        next_carrier = stack / next_wing_id / next_carrier_id

        router.route(carrier / 0 / 8, next_carrier / 1 / 12)
        router.route(carrier / 0 / 9, next_carrier / 1 / 13)
        router.route(carrier / 0 / 10, next_carrier / 1 / 14)
        router.route(carrier / 0 / 11, next_carrier / 1 / 15)

        router.route(carrier / 0 / 12, prev_carrier / 0 / 8)
        router.route(carrier / 0 / 13, prev_carrier / 0 / 9)
        router.route(carrier / 0 / 14, prev_carrier / 0 / 10)
        router.route(carrier / 0 / 15, prev_carrier / 0 / 11)


def test_carrier_loops():
    """
    Test short and long loop routing configurations.

    First tests short loops within each wing of stack 0, then enables
    long loop mode and tests routing across the entire stack.
    """
    router = build()
    stack = Loc.new_stack(0)
    short_loop_helper(router, stack / 0)
    short_loop_helper(router, stack / 1)

    router.set_long_loop(stack)
    long_loop_helper(router, stack)


def test_wing():
    """
    Test routing between carriers via wing-level ST-blocks.

    Lanes 16-31 can route between carriers/wings via ST-blocks.
    These routes have directionality constraints based on lane
    numbers and wing positions.
    """
    router = build()
    stack = Loc.new_stack(0)

    router.route(stack / 0 / 0 / 0 / 16, stack / 1 / 1 / 1 / 16)
    router.route(stack / 1 / 1 / 1 / 31, stack / 0 / 0 / 0 / 31)

    with raises(RoutingException):
        router.route(stack / 1 / 1 / 1 / 16, stack / 0 / 0 / 0 / 16)

    with raises(RoutingException):
        router.route(stack / 0 / 0 / 0 / 31, stack / 1 / 1 / 1 / 31)

    with raises(RoutingException):
        router.route(stack / 0 / 0 / 0 / 31, stack / 1 / 1 / 1 / 17)

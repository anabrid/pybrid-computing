# Copyright (c) 2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
Tests for DummyDAC LUCIDAC mode.

These tests verify that DummyDAC can emulate a LUCIDAC with a single carrier
and FrontPlane entity, as opposed to the default multi-carrier REDAC mode.

Updated for Sprint 1: front_panel -> front_plane rename.
"""

import pytest

from pybrid.mock import DummyDAC, DummyDACConfig
from pybrid.redac.controller import Controller
from tests.conftest import get_test_port


@pytest.mark.asyncio
async def test_lucidac_mode_entity_tree():
    """
    Start DummyDAC with lucidac_mode=True. Connect and describe.
    Assert single carrier, /FP present.

    This test verifies that when lucidac_mode is enabled, the DummyDAC
    builds an entity tree that matches a real LUCIDAC device:
    - Exactly one carrier (not two as in default REDAC mode)
    - FrontPlane entity present at /FP path
    """
    config = DummyDACConfig(lucidac_mode=True)
    port = get_test_port(0)

    async with DummyDAC("127.0.0.1", port, config) as dac:
        dac_port = dac._server.sockets[0].getsockname()[1]

        async with Controller(standalone=True) as ctrl:
            await ctrl.add_device("127.0.0.1", dac_port)

            # Should have exactly 1 carrier (LUCIDAC mode)
            assert len(ctrl.computer.carriers) == 1, (
                f"Expected 1 carrier in LUCIDAC mode, got {len(ctrl.computer.carriers)}"
            )

            # Get the carrier
            carrier = ctrl.computer.carriers[0]

            # Check for FrontPlane on carrier (parsed from entity tree)
            fp = getattr(carrier, "front_plane", None)
            assert fp is not None, (
                "Expected FrontPlane to be present in LUCIDAC mode "
                "(carrier.front_plane should not be None). "
                "The attribute may not have been renamed from 'front_panel' yet."
            )

            # LUCIDAC doesn't have T-block (only REDAC has it)
            assert carrier.tblock is None, (
                "LUCIDAC mode should NOT have T-block"
            )


@pytest.mark.asyncio
async def test_lucidac_mode_fp_parsed_by_carrier():
    """
    Start DummyDAC with lucidac_mode=True. Add device to Controller.
    Assert carrier.front_plane is not None.

    This test verifies that the Controller correctly parses the FrontPlane
    entity from the entity tree and assigns it to the carrier.front_plane
    attribute.
    """
    config = DummyDACConfig(lucidac_mode=True)
    port = get_test_port(1)

    async with DummyDAC("127.0.0.1", port, config) as dac:
        dac_port = dac._server.sockets[0].getsockname()[1]

        async with Controller(standalone=True) as ctrl:
            await ctrl.add_device("127.0.0.1", dac_port)

            # Get the carrier
            carrier = ctrl.computer.carriers[0]

            # Carrier should have front_plane attribute set
            assert hasattr(carrier, "front_plane"), (
                "Carrier should have front_plane attribute"
            )
            fp = getattr(carrier, "front_plane", None)
            assert fp is not None, (
                "Carrier.front_plane should be set in LUCIDAC mode"
            )


@pytest.mark.asyncio
async def test_default_mode_no_fp():
    """
    Start DummyDAC with lucidac_mode=False (default).
    Assert no FP on carriers.

    This test verifies backward compatibility: when lucidac_mode is disabled
    or not specified, DummyDAC behaves as before with 2 carriers and no
    FrontPlane entities.
    """
    config = DummyDACConfig(lucidac_mode=False)
    port = get_test_port(2)

    async with DummyDAC("127.0.0.1", port, config) as dac:
        dac_port = dac._server.sockets[0].getsockname()[1]

        async with Controller(standalone=True) as ctrl:
            await ctrl.add_device("127.0.0.1", dac_port)

            # Should have 2 carriers (default REDAC mode)
            assert len(ctrl.computer.carriers) == 2, (
                f"Expected 2 carriers in default mode, got {len(ctrl.computer.carriers)}"
            )

            # Check that no carrier has a FrontPlane
            for carrier in ctrl.computer.carriers:
                # Check carrier.front_plane attribute
                assert hasattr(carrier, "front_plane"), (
                    "Carrier should have front_plane attribute"
                )
                fp = getattr(carrier, "front_plane", None)
                assert fp is None, (
                    "Carrier.front_plane should be None in default mode"
                )

                # REDAC mode SHOULD have T-block
                assert carrier.tblock is not None, (
                    "Default REDAC mode should have T-block"
                )

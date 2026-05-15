# Copyright (c) 2025 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
Integration tests for LucipyWrapper single-device workflow.

These tests verify ``LucipyWrapper``, which uses a single-controller design:
one controller is created and all devices are added to it, leveraging the
REDAC controller's distributed run machinery.

Uses DummyDAC in LUCIDAC mode for testing.
"""

import logging
import os

import pytest

from pybrid.lucipy import LUCIDAC
from pybrid.lucipy.circuits import Circuit
from pybrid.lucipy.computer import LucipyWrapper
from pybrid.mock import DummyDAC, DummyDACConfig
from tests.conftest import get_test_port

# DummyDAC returns a smaller data array than real hardware for the OP_END
# final-values callback.  The controller's handle_run_data_end tries to
# index beyond that array, causing a harmless IndexError logged at ERROR
# level.  Suppress during run tests.
_PROTOCOL_LOGGER = "pybrid.redac.protocol.protocol"

# Port base offset -- avoids collision with other test files.
_PORT_BASE = 300


class TestLucipyWrapperSingleDevice:
    """Tests for single-device LucipyWrapper workflow."""

    @pytest.mark.asyncio
    async def test_single_device_init_and_run(self):
        """_ensure_controller() initializes the controller and discovers exactly 1 carrier."""
        config = DummyDACConfig(lucidac_mode=True)
        port = get_test_port(_PORT_BASE)

        async with DummyDAC("127.0.0.1", port, config) as dac:
            dac_port = dac._server.sockets[0].getsockname()[1]

            wrapper = LucipyWrapper(f"tcp://127.0.0.1:{dac_port}")

            # The new wrapper uses lazy init via _ensure_controller()
            if not hasattr(wrapper, "_ensure_controller"):
                pytest.fail("LucipyWrapper._ensure_controller() not yet implemented " "(still using old LUCIStack API)")

            await wrapper._ensure_controller()

            assert wrapper._controller is not None, "Controller should be initialized after _ensure_controller()"
            assert (
                len(wrapper._controller.computer.carriers) == 1
            ), "Single-device wrapper should discover exactly 1 carrier"

            await wrapper.close()

    @pytest.mark.asyncio
    async def test_lucidac_alias_works(self):
        """LUCIDAC alias resolves to LucipyWrapper for backward compatibility."""
        config = DummyDACConfig(lucidac_mode=True)
        port = get_test_port(_PORT_BASE + 1)

        async with DummyDAC("127.0.0.1", port, config) as dac:
            dac_port = dac._server.sockets[0].getsockname()[1]

            luci = LUCIDAC(f"tcp://127.0.0.1:{dac_port}")

            # The LUCIDAC alias must resolve to LucipyWrapper.
            try:
                from pybrid.lucipy.computer import LucipyWrapper as _NewWrapper

                assert isinstance(luci, _NewWrapper), "LUCIDAC alias should create a LucipyWrapper instance"
            except ImportError:
                pytest.fail(
                    "pybrid.lucipy.computer.LucipyWrapper not yet available "
                    "(LUCIDAC alias still points to old LUCIStack)"
                )

    @pytest.mark.asyncio
    async def test_env_var_fallback(self):
        """LucipyWrapper() with no args uses LUCIDAC_ENDPOINT env var to resolve the endpoint."""
        config = DummyDACConfig(lucidac_mode=True)
        port = get_test_port(_PORT_BASE + 2)

        async with DummyDAC("127.0.0.1", port, config) as dac:
            dac_port = dac._server.sockets[0].getsockname()[1]

            original_env = os.environ.get("LUCIDAC_ENDPOINT")
            try:
                os.environ["LUCIDAC_ENDPOINT"] = f"tcp://127.0.0.1:{dac_port}"

                wrapper = LucipyWrapper()

                # The wrapper should have resolved the endpoint from env
                if not hasattr(wrapper, "_ensure_controller"):
                    pytest.fail(
                        "LucipyWrapper._ensure_controller() not yet " "implemented (still using old LUCIStack API)"
                    )

                await wrapper._ensure_controller()

                assert wrapper._controller is not None, "Controller should be initialized via env var endpoint"
                assert len(wrapper._controller.computer.carriers) == 1, "Env var endpoint should resolve to 1 carrier"

                await wrapper.close()

            finally:
                if original_env is not None:
                    os.environ["LUCIDAC_ENDPOINT"] = original_env
                else:
                    os.environ.pop("LUCIDAC_ENDPOINT", None)

    @pytest.mark.asyncio
    async def test_controller_cleanup(self):
        """After close(), _controller is None."""
        config = DummyDACConfig(lucidac_mode=True)
        port = get_test_port(_PORT_BASE + 3)

        async with DummyDAC("127.0.0.1", port, config) as dac:
            dac_port = dac._server.sockets[0].getsockname()[1]

            wrapper = LucipyWrapper(f"tcp://127.0.0.1:{dac_port}")

            if not hasattr(wrapper, "_ensure_controller"):
                pytest.fail("LucipyWrapper._ensure_controller() not yet implemented " "(still using old LUCIStack API)")

            await wrapper._ensure_controller()
            assert wrapper._controller is not None

            await wrapper.close()

            assert wrapper._controller is None, "After close(), _controller should be None"

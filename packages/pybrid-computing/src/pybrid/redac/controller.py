# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later
import asyncio
import logging
import typing
import warnings

from uuid import UUID
from typing import List, Optional

import numpy as np

import pybrid.base.proto.main_pb2 as pb
from pybrid.base.hybrid.controller import BaseController
from pybrid.redac.computer import REDAC
from pybrid.redac.device import Device
from pybrid.redac.entities import Path
from pybrid.redac.run import Run, RunState, RunError
from pybrid.base.hybrid.listeners import SampleListener

logger = logging.getLogger(__name__)


class DistributedRunState:
    #: A dictionary tracking each possible RunState for each involved carrier
    _states: dict[Path, dict[RunState, asyncio.Event]]
    #: The run which state we are tracking
    run: Run
    #: The run once it's done
    _any_error_future: asyncio.Future

    def __init__(self, run, paths: typing.Optional[typing.Iterable[Path]] = None):
        self.run = run
        self._any_error_future = asyncio.Future()
        self._states = {}
        if paths:
            self.add_paths(*paths)

    def get_involved_paths(self) -> typing.Iterable[Path]:
        return self._states.keys()

    def track(self, path: Path, state: RunState, reason: str | None = None):
        self._states[path][state].set()
        if state == RunState.ERROR and not self._any_error_future.done():
            self._any_error_future.set_exception(RunError(f"Error on entity {path}: {reason or 'Unknown Error'}"))

        self._update_run_state()

    def _update_run_state(self):
        """Update run.state to the highest state all devices have reached.

        ERROR on any device immediately sets run.state to ERROR; otherwise
        run.state advances only when all devices agree.
        """
        if not self._states:
            return

        for path_states in self._states.values():
            if path_states[RunState.ERROR].is_set():
                self.run.state = RunState.ERROR
                return

        state_order = [
            RunState.NEW,
            RunState.QUEUED,
            RunState.TAKE_OFF,
            RunState.IC,
            RunState.OP,
            RunState.OP_END,
            RunState.DONE,
        ]

        for state in reversed(state_order):
            all_reached = all(
                path_states[state].is_set()
                for path_states in self._states.values()
            )
            if all_reached:
                self.run.state = state
                return

    def status(self, state: RunState):
        reached = []
        notreached = []
        for entity in self._states.values():
            if entity[state].is_set():
                reached.append(entity)
            else:
                notreached.append(entity)
        return reached, notreached

    async def wait_all(self, state: RunState):
        """Wait for all entities to reach the target state.

        Raises :class:`RunError` if any entity enters ``RunState.ERROR`` while waiting.
        """
        waiting_for = {asyncio.create_task(states[state].wait()): entity for entity, states in self._states.items()}
        try:
            while waiting_for:
                # Short-circuit via _any_error_future if any entity enters RunState.ERROR.
                waiting_or_error = [self._any_error_future, *waiting_for]
                done, _ = await asyncio.wait(waiting_or_error, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    if exc := task.exception():
                        raise exc
                    else:
                        waiting_for.pop(task)
        except asyncio.CancelledError:
            # Convert to TimeoutError so asyncio.timeout() and asyncio.wait_for()
            # preserve the error description.
            raise asyncio.TimeoutError(f"Entities {list(map(str, waiting_for.values()))} did not reach {state}.")
        finally:
            for task in waiting_for:
                task.cancel()
            await asyncio.gather(*waiting_for, return_exceptions=True)

    def add_paths(self, *paths: Path):
        """Add paths to tracking; raises :class:`ValueError` if a path is already tracked."""
        for path in paths:
            if path in self._states:
                raise ValueError(f"Path {path} is already being tracked.")
            self._states[path] = {state: asyncio.Event() for state in RunState}


class Controller(BaseController):
    """Abstraction of the REDAC hybrid controller.

    Inherits device management, run tracking, and lifecycle from
    :class:`~pybrid.base.hybrid.controller.BaseController`.

    .. deprecated::
        The ``standalone`` constructor parameter is deprecated; use
        ``sync_impl`` instead.  Passing both raises :class:`ValueError`.
    """

    #: Representation of the current configuration of the analog computer.
    computer: REDAC

    _raw_entity_dict: dict
    _ongoing_runs: dict[UUID, DistributedRunState]
    #: Number of clusters per carrier (used for M-block indexing in run data)
    _clusters_per_carrier: dict[Path, int]

    #: Listeners that forward received UDP data directly to the user
    sample_listeners: typing.List[SampleListener] = []


    def __init__(self):
        super().__init__()
        self.computer = REDAC(entities=[])
        self._raw_entity_dict = dict()
        self._ongoing_runs = dict()
        self._clusters_per_carrier = dict()

    @classmethod
    def get_run_implementation(cls) -> typing.Type[Run]:
        return Run

    @classmethod
    def get_computer_type(cls) -> typing.Type[REDAC]:
        return REDAC

    @property
    def protocols(self) -> dict:
        """Deprecated.  Use ``connection_manager.connections`` instead.

        .. deprecated::
        """
        warnings.warn(
            "controller.protocols is deprecated. "
            "Use controller.connection_manager.connections instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.connection_manager.connections

    @property
    def devices(self) -> dict:
        """Deprecated.  Use ``connection_manager.connections`` instead.

        .. deprecated::
        """
        warnings.warn(
            "controller.devices is deprecated. "
            "Use controller.connection_manager.connections instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.connection_manager.connections

    @devices.setter
    def devices(self, value) -> None:
        """Deprecated setter — silently ignored."""
        warnings.warn(
            "Setting controller.devices is deprecated. "
            "Use controller.connection_manager.connections instead.",
            DeprecationWarning,
            stacklevel=2,
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await super().__aexit__(exc_type, exc_val, exc_tb)

    async def add_device(self, host, port, specification: Optional[pb.Module] = None):
        """Add a device endpoint to this controller.

        After the base class discovers and connects to the device, walks
        newly discovered entities to update :attr:`computer` with new carriers.

        `specification` argument is only used for the simulator which parses
        its entities from a file as the simulator, being hardware-agnostic,
        does not return a hardware specification.
        """
        # Snapshot the description count before the call so we know which
        # entities were freshly discovered.
        prev_entity_count = len(self.connection_manager.cache_descriptions.items)

        await super().add_device(host, port, specification)

        new_items = self.connection_manager.cache_descriptions.items[prev_entity_count:]
        for item in new_items:
            if not item.HasField("entity_specification"):
                continue
            entity = item.entity_specification.entity
            root_path = Path.parse(entity.id.strip("/"))

            # Use the LUCIDAC-capable deserializer so that FP children in the
            # entity tree are recognised regardless of the computer model type.
            # LUCIDACDeserializer is a strict superset of the REDAC base and
            # produces identical results for non-LUCIDAC entities.
            from pybrid.lucidac.protocol.serializer import LUCIDACDeserializer
            deserializer = LUCIDACDeserializer()
            result = deserializer.deserialize_specification(entity, root_path)
            # The firmware may report a single CARRIER entity (standalone mode)
            # or a DEVICE entity wrapping multiple carriers (proxy mode).
            if isinstance(result, Device):
                carriers = result.carriers
            else:
                carriers = [result]
            for carrier in carriers:
                self.computer.add_carrier(carrier)
                self._clusters_per_carrier[carrier.path] = len(carrier.clusters)
            self._raw_entity_dict[entity.id] = entity

    async def forward_set_config(self, message: pb.ConfigCommand):
        """Forward a config command via a Session.

        .. deprecated::
            Use ``session.set_module(module).execute()`` instead.
        """
        warnings.warn(
            "controller.forward_set_config() is deprecated. "
            "Use session.set_module(module).execute() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        from pybrid.redac.session import Session
        session = Session(self)
        session.set_module(message.module)
        result = await session.execute()
        return result

    async def set_computer(self, computer: REDAC):
        """Change the configuration of all carrier boards.

        .. deprecated::
            Use ``session.set_config(computer).execute()`` instead.
        """
        warnings.warn(
            "controller.set_computer() is deprecated. "
            "Use session.set_config(computer).execute() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        from pybrid.redac.session import Session
        session = Session(self)
        session.set_config(computer)
        await session.execute()

    async def start_and_await_run(self, run: typing.Optional[Run] = None, timeout=100) -> Run:
        """Start a run and wait for completion.

        .. deprecated::
            Use ``session.run(config).execute()`` instead.
        """
        warnings.warn(
            "controller.start_and_await_run() is deprecated. "
            "Use session.run(config).execute() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        from pybrid.redac.session import Session
        session = Session(self)

        # For backwards compatibility: calibrate before the run, as it used to
        # happen implicitly when issuing a "run" command.
        all_paths = list(self.connection_manager.connections.keys())
        leader = str(all_paths[0]) if all_paths else ""
        session.calibrate(leader=leader)

        if run is None:
            session.run(timeout=timeout)
        else:
            session.run(run.config, daq=run.daq, timeout=timeout)
        result = await session.execute()
        return result[0] if result else run

    async def register_external_entities(self):
        """Distribute carrier MACs and IP addresses to every connected device.

        Builds a map of ``{carrier_mac: ip_octets}`` from all carriers
        in :attr:`computer` and sends a ``RegisterExternalEntitiesCommand`` to
        each unique backend connection.
        """

        # TODO: reinstate once implemented in the firmware
        logger.warning("RegisterExternalEntities command skipped...")
        return

        if not self.computer.carriers:
            return

        entities: dict[str, tuple[int, int, int, int]] = {}
        for carrier in self.computer.carriers:
            conn = self.connection_manager.get_connection(carrier.path)
            host = conn.control.remote_host
            octets = tuple(int(x) for x in host.split("."))
            entities[str(carrier.path)] = octets

        for conn in self.connection_manager.get_unique_connections():
            result = await conn.control.register_external_entities(entities)
            result.raise_on_error()

    async def reset(self, keep_calibration: bool = True, sync: bool = True):
        """Reset all carrier boards to initial configuration."""
        for conn in self.connection_manager.get_unique_connections():
            if hasattr(conn, "control") and conn.control is not None:
                result = await conn.control.reset(keep_calibration=keep_calibration, sync=sync)
                result.raise_on_error()

# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later
import asyncio
import logging
import typing
import warnings
from uuid import UUID

import numpy as np

import pybrid.base.proto.main_pb2 as pb
from pybrid.base.hybrid.controller import BaseController
from pybrid.redac.computer import REDAC
from pybrid.redac.device import Device
from pybrid.redac.entities import Path
from pybrid.redac.run import Run, RunState, RunError
from pybrid.redac.sync import Sync, SyncImplementationType
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

    #: Allows synching via USB
    sync: typing.Optional[Sync]

    def __init__(
        self,
        sync_impl: SyncImplementationType = SyncImplementationType.NATIVE,
        *,
        standalone: typing.Optional[bool] = None,
    ):
        """
        :param sync_impl: Synchronisation strategy.  Defaults to
            :attr:`~pybrid.redac.sync.SyncImplementationType.NATIVE`.
        :param standalone: Deprecated.  Pass ``sync_impl`` instead.
        :raises ValueError: If both ``sync_impl`` and ``standalone`` are supplied.
        """
        if standalone is not None:
            if sync_impl is not SyncImplementationType.NATIVE:
                raise ValueError(
                    "Cannot pass both 'standalone' and 'sync_impl'. "
                    "Use 'sync_impl' only."
                )
            warnings.warn(
                "The 'standalone' parameter is deprecated. "
                "Use 'sync_impl=SyncImplementationType.NATIVE' (True) or "
                "'sync_impl=SyncImplementationType.USBSPI' (False) instead.",
                DeprecationWarning,
                stacklevel=2,
            )
            sync_impl = (
                SyncImplementationType.NATIVE
                if standalone
                else SyncImplementationType.USBSPI
            )

        super().__init__(sync_impl=sync_impl)
        self.computer = REDAC(entities=[])
        self._raw_entity_dict = dict()
        self._ongoing_runs = dict()
        self._clusters_per_carrier = dict()
        self.sync = None

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

    @property
    def standalone(self) -> bool:
        """Deprecated.  Use ``sync_impl`` instead.

        .. deprecated::
        """
        warnings.warn(
            "controller.standalone is deprecated. "
            "Use controller.sync_impl instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.sync_impl == SyncImplementationType.NATIVE

    @standalone.setter
    def standalone(self, value: bool) -> None:
        """Deprecated setter.  Updates :attr:`sync_impl` accordingly.

        .. deprecated::
        """
        warnings.warn(
            "Setting controller.standalone is deprecated. "
            "Use controller.sync_impl instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        self.sync_impl = (
            SyncImplementationType.NATIVE
            if value
            else SyncImplementationType.USBSPI
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await super().__aexit__(exc_type, exc_val, exc_tb)

    def enable_sync(self):
        """Enable the hardware synchronisation subsystem.

        Creates a :class:`~pybrid.redac.sync.Sync` instance if one has not
        already been created.  Exceptions are logged and swallowed so that
        sync-unavailability does not propagate to callers.
        """
        if self.sync:
            return
        try:
            self.sync = Sync()
        except Exception as e:
            logger.exception(e)

    async def add_device(self, host, port, name=None):
        """Add a device endpoint to this controller.

        After the base class discovers and connects to the device, walks
        newly discovered entities to update :attr:`computer` with new carriers.
        """
        # Snapshot the description count before the call so we know which
        # entities were freshly discovered.
        prev_entity_count = len(self.connection_manager.cache_descriptions.entities)

        await super().add_device(host, port)

        new_entities = self.connection_manager.cache_descriptions.entities[prev_entity_count:]
        for entity in new_entities:
            root_path = Path.parse(entity.id.strip("/"))
            device = Device.create_from_entity_type_tree(root_path, entity)
            for carrier in device.carriers:
                self.computer.add_carrier(carrier)
                self._clusters_per_carrier[carrier.path] = len(carrier.clusters)
            self._raw_entity_dict[entity.id] = entity

    async def forward_set_config(self, message: pb.ConfigCommand):
        """Forward a config command via a Session.

        .. deprecated::
            Use ``session.set_config_bundle(bundle).execute()`` instead.
        """
        warnings.warn(
            "controller.forward_set_config() is deprecated. "
            "Use session.set_config_bundle(bundle).execute() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        from pybrid.redac.session import Session
        session = Session(self)
        session.set_config_bundle(message.bundle)
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
        if run is None:
            session.run(timeout=timeout)
        else:
            session.run(run.config, daq=run.daq, timeout=timeout)
        result = await session.execute()
        return result[0] if result else run

    async def reset(self, keep_calibration: bool = True, sync: bool = True):
        """Reset all carrier boards to initial configuration."""
        for conn in self.connection_manager.get_unique_connections():
            if hasattr(conn, "control") and conn.control is not None:
                result = await conn.control.reset(keep_calibration=keep_calibration, sync=sync)
                result.raise_on_error()

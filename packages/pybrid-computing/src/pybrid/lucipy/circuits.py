#!/usr/bin/env python3

"""
Lucipy Circuits: High-level circuit definition API for the LUCIDAC.

This module provides the Circuit class, which offers a user-friendly interface
for programming the LUCIDAC analog computer. Elements are allocated greedily
and connections are set up using validate-then-commit semantics on an internal
pybrid LUCIDAC object.

Element types:
    - Integrator: 8 available (M0 block, lanes 0-7)
    - Multiplier: 4 available (M1 block, lanes 8-11), with inputs a/b
    - Identity: 4 available (M1 block, outputs 12-15, source-only),
      created from multiplier inputs via m.a.id() / m.b.id()
    - Constant: single constant giver (M-block output 15 for lanes 0-15,
      output 14 for lanes 16-31)
    - Input: 8 ACL_IN ports (lanes 24-31)
    - Output: 8 ACL_OUT ports (lanes 24-31)

Lane allocation:
    General signals use lanes 0-31 (allocated greedily starting from 0).
    Lanes 24-31 are shared between general signals and ACL I/O ports.
    A lane occupied by a general signal cannot be used for an ACL port
    (and vice versa).
"""

import math
import uuid
import warnings

# for protobuf export
from pybrid.base.proto import main_pb2 as pb
from pybrid.redac.carrier import ADCChannel

from pybrid.lucipy._compat import deprecated
from pybrid.lucipy.helpers import Helpers
from pybrid.lucipy.elements import (  # noqa: F401 — re-exported for backward compat
    Integrator,
    _MulInput,
    Multiplier,
    Identity,
    Constant,
    Input,
    Output,
    Element,
)


class Circuit:
    """
    The Circuit class provides a user-friendly interface for programming the LUCIDAC.

    Internally creates and manipulates a pybrid LUCIDAC object. Elements are
    allocated greedily and connections set up using validate-then-commit semantics.
    """

    def __init__(self, mac: str):
        """Initialize a new Circuit with an internal pybrid LUCIDAC.

        :param mac: MAC address string for the carrier (e.g. "AA-BB-CC-DD-EE-FF").
        """
        # Unique identifier for ownership checks
        self._circuit_id = uuid.uuid4()

        # Internal pybrid LUCIDAC
        self._lucidac = Helpers.create_minimal_lucidac(mac)
        self._carrier = self._lucidac.entities[0]
        self._cluster = self._carrier.clusters[0]

        # Allocation tracking
        self._integrators_used = [False] * 8
        self._multipliers_used = [False] * 4
        self._constants_allocated = 0
        self._acl_in_used = [False] * 8
        self._acl_out_used = [False] * 8

        # Lane allocation tracking (lanes 0-31; lanes 24-31 are shared
        # between general signals and ACL I/O ports)
        self._general_lanes_used = [False] * 32

        # Identity output tracking: M-block outputs 14/15 that have been
        # used as sources in connect(). Needed to detect constant-giver
        # shadowing (outputs 14/15 are shared with the constant giver).
        self._identity_outputs_connected = set()

        # ADC channel tracking — stored directly on the carrier
        self._carrier.adc_config = [None] * 8  # None = free, ADCChannel = occupied

        # Probe index counter — auto-incremented by _probe_adc()
        self._next_probe_index: int = 0

        # Initialize IBlock outputs properly (each output needs its own independent set)
        self._cluster.iblock.outputs = [set() for _ in range(16)]

    def int(self, ic=0.0, slow=False) -> Integrator:
        """
        Allocate an integrator with optional initial condition and speed setting.

        :param ic: Initial condition in [-1.0, 1.0], default 0.0
        :param slow: If True, use slow time constant (100), else fast (10000)
        :returns: Integrator wrapper with id and lane
        :raises ValueError: If all 8 integrators are already allocated
        """
        idx = Helpers.next_free(self._integrators_used)
        if idx is None:
            raise ValueError("No free integrators available, all 8 are occupied.")
        self._integrators_used[idx] = True
        self._cluster.m0block.elements[idx].computation.ic = ic
        self._cluster.m0block.elements[idx].computation.k = 100 if slow else 10_000
        return Integrator(id=idx, lane=idx, _circuit_id=self._circuit_id)

    def mul(self) -> Multiplier:
        """
        Allocate a multiplier.

        :returns: Multiplier wrapper with id and lane
        :raises ValueError: If all 4 multiplier slots are used by multipliers or full identity pairs
        """
        idx = Helpers.next_free(self._multipliers_used)
        if idx is None:
            raise ValueError("No free multipliers available, all 4 are occupied.")

        self._multipliers_used[idx] = True
        return Multiplier(id=idx, lane=8 + idx, _circuit_id=self._circuit_id)

    def id(self, offset: int = None) -> Identity:
        """
        Removed: use ``multiplier_input.id()`` instead.

        Identity elements must now be created from multiplier inputs::

            m = circuit.mul()
            id_a = m.a.id()
            id_b = m.b.id()

        :raises RuntimeError: Always
        """
        raise RuntimeError(
            "Circuit.id(offset) has been removed. "
            "Create identity elements from multiplier inputs instead: "
            "m = circuit.mul(); id_a = m.a.id(); id_b = m.b.id()"
        )

    def const(self, value=1.0) -> Constant:
        """
        Allocate a constant source.

        :param value: Constant value (passed to UBlock.set_constant)
        :returns: Constant wrapper with id
        :raises ValueError: If both constant slots are occupied
        """
        if self._constants_allocated >= 2:
            raise ValueError("No free constant slots available, all 2 are occupied.")

        # Check if any Identity output 14/15 was already connected — the
        # constant giver shadows these M-block outputs once activated.
        shadowed = self._identity_outputs_connected & {14, 15}
        if shadowed:
            warnings.warn(
                f"Activating the constant giver shadows Identity M-block "
                f"output(s) {sorted(shadowed)}.  The constant giver uses "
                f"the same physical outputs (14 for lanes 16-31, 15 for "
                f"lanes 0-15).  Any previously connected Identity paths on "
                f"these outputs will receive the constant value instead of "
                f"the identity passthrough.",
                UserWarning,
                stacklevel=2,
            )

        idx = self._constants_allocated
        self._constants_allocated += 1
        self._cluster.ublock.set_constant(value)
        return Constant(id=idx, _circuit_id=self._circuit_id)

    def input(self, port=None) -> Input:
        """
        Allocate an ACL_IN port.

        :param port: Specific port (0-7), or None for greedy allocation
        :returns: Input wrapper with port and lane
        :raises ValueError: If the requested port is already allocated or all ports are used
        """
        if port is None:
            port = Helpers.next_free(self._acl_in_used)
            if port is None:
                raise ValueError("No free ACL_IN port available, all 8 are occupied.")
        elif self._acl_in_used[port]:
            raise ValueError(f"ACL_IN port {port} is already allocated.")
        lane = 24 + port
        if self._general_lanes_used[lane]:
            raise ValueError(
                f"ACL_IN port {port} (lane {lane}) is already used by a general signal. "
                f"Try a different port whose lane is not occupied."
            )
        self._acl_in_used[port] = True
        self._carrier.acl_select[port] = "EXTERNAL"
        return Input(port=port, lane=lane, _circuit_id=self._circuit_id)

    def output(self, port=None) -> Output:
        """
        Allocate an ACL_OUT port.

        :param port: Specific port (0-7), or None for greedy allocation
        :returns: Output wrapper with port and lane
        :raises ValueError: If the requested port is already allocated or all ports are used
        """
        if port is None:
            port = Helpers.next_free(self._acl_out_used)
            if port is None:
                raise ValueError("No free ACL_OUT port available, all 8 are occupied.")
        elif self._acl_out_used[port]:
            raise ValueError(f"ACL_OUT port {port} is already allocated.")
        lane = 24 + port
        if self._general_lanes_used[lane]:
            raise ValueError(
                f"ACL_OUT port {port} (lane {lane}) is already used by a general signal. "
                f"Try a different port whose lane is not occupied."
            )
        self._acl_out_used[port] = True
        self._carrier.acl_select[port] = "EXTERNAL"
        return Output(port=port, lane=lane, _circuit_id=self._circuit_id)

    def connect(self, source, target, weight: float = 1.0):
        """
        Connect a source element to a target element with given weight.

        Uses validate-then-commit semantics: checks that enough lanes are
        available before making any changes to internal state.

        :param source: Source element
        :param target: Target element
        :param weight: Connection weight (can be >1.0 with upscaling)
        :raises ValueError: If elements belong to a different circuit or
            not enough lanes are available
        """
        # Ownership check: reject elements from a different circuit
        source_cid = getattr(source, '_circuit_id', None)
        target_cid = getattr(target, '_circuit_id', None)
        if source_cid is None or target_cid is None:
            raise ValueError("Dangling elements without a circuit reference found!")

        if source_cid is not None and source_cid != self._circuit_id:
            raise ValueError(
                f"Source {type(source).__name__} belongs to a different Circuit. "
                f"All elements in a connect() call must belong to the same circuit."
            )
        if target_cid is not None and target_cid != self._circuit_id:
            raise ValueError(
                f"Target {type(target).__name__} belongs to a different Circuit. "
                f"All elements in a connect() call must belong to the same circuit."
            )

        is_acl_in = isinstance(source, Input)
        is_acl_out = isinstance(target, Output)
        is_constant = isinstance(source, Constant)
        is_identity = isinstance(source, Identity)

        # For constants, the M-block output depends on the allocated lane
        # and is determined per-lane below.
        if is_constant:
            source_output_lane = None
        elif not hasattr(source, 'source_output_lane'):
            raise TypeError(f"Unsupported source type: {type(source)}")
        else:
            source_output_lane = source.source_output_lane()

        if not hasattr(target, 'target_m_input'):
            raise TypeError(f"Unsupported target type: {type(target)}")
        target_m_input = target.target_m_input()

        # Warn if Identity output 14 or 15 is used while constant giver is on
        if is_identity and source.offset in (2, 3):
            mblock_output = 12 + source.offset  # 14 or 15
            if self._cluster.ublock.constant:
                warnings.warn(
                    f"Identity output {mblock_output} (offset={source.offset}) "
                    f"is shadowed by the constant giver.  The constant giver "
                    f"uses the same physical M-block output "
                    f"({mblock_output} for lanes "
                    f"{'16-31' if mblock_output == 14 else '0-15'}).  "
                    f"This identity path will receive the constant value "
                    f"instead of the identity passthrough.",
                    UserWarning,
                    stacklevel=2,
                )
            self._identity_outputs_connected.add(mblock_output)

        # For ACL_IN/ACL_OUT, the lane is fixed; do not set C-block as inputs
        # are wired in behind the C- and in before the I-block
        if is_acl_in:
            acl_lane = source.lane
            # IBlock: connect ACL lane to target M-block input
            self._cluster.iblock.connect(acl_lane, target_m_input, force=False)
            # UBlock output at ACL lane stays None (ACL_IN bypasses U-block)
            return

        if is_acl_out:
            acl_lane = target.lane
            if abs(weight) > 1.0:
                raise ValueError(
                    f"ACL_OUT weight must be in [-1, 1] (no I-block upscaling "
                    f"available on output path), got {weight}."
                )
            # For constants, determine output from the ACL lane range
            acl_source = (
                Helpers.constant_output_for_lane(acl_lane)
                if is_constant else source_output_lane
            )
            # Commit: set UBlock output to source, set CBlock coefficient
            self._cluster.ublock.connect(acl_source, acl_lane, force=False)
            self._cluster.cblock.elements[acl_lane].computation.factor = weight
            # IBlock is NOT connected for ACL_OUT
            return

        # Standard connection: allocate lane(s) from general pool (0-31)
        n_lanes = max(1, math.ceil(abs(weight) / 8))

        # VALIDATE: check that n_lanes lanes are available
        available_lanes = []
        for lane in range(32):
            if not self._general_lanes_used[lane]:
                # Skip lanes reserved by ACL I/O ports
                if lane >= 24:
                    port = lane - 24
                    if self._acl_in_used[port] or self._acl_out_used[port]:
                        continue
                available_lanes.append(lane)
        if len(available_lanes) < n_lanes:
            raise ValueError(
                f"Not enough free lanes for connection with weight={weight} "
                f"(need {n_lanes} lanes, only {len(available_lanes)} available)."
            )

        # COMMIT: allocate lanes and configure blocks
        lanes_to_use = available_lanes[:n_lanes]
        weight_per_lane = weight / n_lanes

        for lane in lanes_to_use:
            self._general_lanes_used[lane] = True

            # For constants, determine M-block output from the lane range
            lane_source = (
                Helpers.constant_output_for_lane(lane)
                if is_constant else source_output_lane
            )

            # UBlock: connect source output to this lane
            self._cluster.ublock.connect(lane_source, lane, force=False)

            # CBlock: set coefficient
            if abs(weight_per_lane) > 1.0:
                # Upscaling needed
                scaled_factor = weight_per_lane / 8
                self._cluster.cblock.elements[lane].computation.factor = scaled_factor
                self._cluster.iblock.upscaling[lane] = True
            else:
                self._cluster.cblock.elements[lane].computation.factor = weight_per_lane

            # IBlock: connect lane to target M-block input
            self._cluster.iblock.connect(lane, target_m_input, force=False)

    def probe(self, source, adc_channel=None, front_port=None, weight=1.0):
        """
        Assign a source element to an ADC channel, or route to ACL_OUT (deprecated).

        Signature-based dispatch:
        - ``probe(source, adc_channel=N)`` — assign ADC channel (canonical)
        - ``probe(source)`` — greedy ADC channel assignment (canonical)
        - ``probe(source, front_port=N, weight=W)`` — deprecated ACL_OUT mode,
          emits DeprecationWarning and delegates to ``output()`` + ``connect()``

        :param source: Source element to probe
        :param adc_channel: Explicit ADC channel (0-7), or None for greedy
        :param front_port: Deprecated. If given, routes to ACL_OUT instead
        :param weight: Connection weight (only used with front_port)
        :returns: ADC channel number, or Output element (if front_port given)
        :raises ValueError: If no free ADC channel or port is available
        """
        # Ownership check
        source_cid = getattr(source, '_circuit_id', None)
        if source_cid is None:
            raise ValueError("Dangling element without a circuit reference found!")
        if source_cid != self._circuit_id:
            raise ValueError(
                f"Source {type(source).__name__} belongs to a different Circuit. "
                f"All elements in a probe() call must belong to the same circuit."
            )

        if front_port is not None and adc_channel is not None:
            raise ValueError(
                "Cannot specify both adc_channel and front_port. "
                "Use adc_channel for ADC measurement, or front_port for ACL_OUT routing."
            )

        if front_port is not None:
            warnings.warn(
                "probe(front_port=...) is deprecated, use output() and connect() instead",
                DeprecationWarning,
                stacklevel=2,
            )
            out = self.output(front_port)
            self.connect(source, out, weight=weight)
            return out

        return self._probe_adc(source, adc_channel)

    def _probe_adc(self, source, adc_channel=None) -> int:
        """
        Internal: assign a source element to an ADC channel for measurement.

        :param source: Source element to measure
        :param adc_channel: Explicit channel (0-7), or None for greedy assignment
        :returns: Assigned ADC channel number
        :raises ValueError: If no free ADC channel is available
        """
        adc_config = self._carrier.adc_config

        if adc_channel is None:
            adc_channel = Helpers.next_free([ch is not None for ch in adc_config])
            if adc_channel is None:
                raise ValueError("No free ADC channel available, all 8 are occupied.")

        if not 0 <= adc_channel <= 7:
            raise ValueError(f"ADC channel must be in range 0-7, got {adc_channel}")

        if adc_config[adc_channel] is not None:
            raise ValueError(f"ADC channel {adc_channel} is already occupied.")

        source_lane = source.source_output_lane()
        probe_index = self._next_probe_index
        self._next_probe_index += 1
        adc_config[adc_channel] = ADCChannel(index=source_lane, probe=probe_index)
        return adc_channel

    def to_computer(self):
        """
        Return the internal pybrid LUCIDAC object.

        Emits a UserWarning because manual changes to the returned object
        are not tracked by the Circuit and may cause inconsistencies.

        :returns: The internal LUCIDAC instance (mutable reference)
        """
        warnings.warn(
            "to_computer() returns a mutable reference to the internal LUCIDAC. "
            "Manual changes will not be tracked by Circuit.",
            UserWarning,
            stacklevel=2,
        )
        return self._lucidac

    def signal_generator(self):
        """
        Return the FrontPanel's signal generator from the internal LUCIDAC.

        :returns: The SignalGenerator instance from the front panel
        """
        carrier = self._lucidac.entities[0] if self._lucidac.entities else None
        if carrier is not None and carrier.front_plane is not None:
            return carrier.front_plane.signal_generator
        return None

    def to_config(self) -> pb.File:
        """
        Convert the circuit to protobuf format suitable for sending to LUCIDAC.

        Serializes the internal pybrid LUCIDAC via the LUCIDAC serializer and
        wraps the result in a ``pb.File``.

        :returns: pb.File containing the serialized circuit configuration.
        """
        from pybrid.lucidac.protocol.serializer import LUCIDACSerializer
        from pybrid.base.proto.versioning import ProtoVersioning

        serializer = LUCIDACSerializer()
        module = serializer.serialize(self._lucidac)

        return pb.File(
            version=ProtoVersioning.current(),
            module=module,
        )

    @deprecated("measure() is deprecated, use probe() instead")
    def measure(self, source, adc_channel=None) -> int:
        """
        Assign a source element to an ADC channel for measurement.

        :param source: Source element to measure
        :param adc_channel: Explicit channel (0-7), or None for greedy assignment
        :returns: Assigned ADC channel number
        """
        return self.probe(source, adc_channel=adc_channel)

    @deprecated("front_input() is deprecated, use input() instead")
    def front_input(self, port):
        """
        Allocate an ACL_IN port.

        :param port: Port number
        :returns: The allocated Input element
        """
        return self.input(port=port)

    @property
    def front_panel(self):
        """
        Deprecated: use signal_generator() instead.

        Returns the FrontPanel from the internal LUCIDAC.
        """
        warnings.warn(
            "front_panel property is deprecated, use signal_generator() instead",
            DeprecationWarning,
            stacklevel=2,
        )
        carrier = self._lucidac.entities[0] if self._lucidac.entities else None
        if carrier is not None:
            return carrier.front_plane
        return None

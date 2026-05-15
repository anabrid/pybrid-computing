"""
Lucipy element dataclasses.

Each dataclass wraps a hardware resource allocated by :class:`Circuit`.
Source-capable elements expose ``source_output_lane()`` and target-capable
elements expose ``target_m_input()`` so that :meth:`Circuit.connect` can
resolve lanes without type-dispatching.

Element types:
    - Integrator: 8 available (M0 block, lanes 0-7)
    - Multiplier: 4 available (M1 block, lanes 8-11), with inputs a/b
    - _MulInput: reference to a specific multiplier input (a or b)
    - Identity: 4 available (M1 block, outputs 12-15, source-only)
    - Constant: single constant giver (output 15 for lanes 0-15,
      output 14 for lanes 16-31)
    - Input: 8 ACL_IN ports (lanes 24-31)
    - Output: 8 ACL_OUT ports (lanes 24-31)
"""

from dataclasses import dataclass, field
from typing import Union


@dataclass
class Integrator:
    """Wrapper for an allocated integrator."""

    id: int  # 0-7, integrator slot index
    lane: int  # same as id (M0 block, offset=0)
    _circuit_id: object = field(default=None, repr=False, compare=False)

    def source_output_lane(self) -> int:
        """Return the M-block output lane for this integrator."""
        return self.lane

    def target_m_input(self) -> int:
        """Return the M-block input lane for this integrator."""
        return self.lane


@dataclass
class _MulInput:
    """Reference to a specific multiplier input (a or b)."""

    mul_id: int  # 0-3, which multiplier slot
    input_idx: int  # 0 for a, 1 for b
    _circuit_id: object = field(default=None, repr=False, compare=False)

    @property
    def lane(self):
        """M-block input lane for this multiplier input."""
        return 8 + 2 * self.mul_id + self.input_idx

    def id(self) -> "Identity":
        """
        Create an identity element from this multiplier input.

        Identity elements are read-taps of M-block inputs, appearing on
        M-block outputs 12-15.  Only multipliers 0 and 1 have identity
        paths (4 outputs total).

        :returns: Identity wrapper with offset = 2 * mul_id + input_idx
        :raises ValueError: If multiplier index >= 2 (no identity path)
        """
        if self.mul_id >= 2:
            raise ValueError(
                f"Multiplier {self.mul_id} has no identity path. "
                f"Only multipliers 0 and 1 have identity outputs "
                f"(M-block outputs 12-15)."
            )
        offset = 2 * self.mul_id + self.input_idx
        return Identity(offset=offset, _circuit_id=self._circuit_id)

    def target_m_input(self) -> int:
        """Return the M-block input lane for this multiplier input."""
        return self.lane


@dataclass
class Multiplier:
    """Wrapper for an allocated multiplier."""

    id: int  # 0-3, multiplier slot index
    lane: int  # 8 + id (M1 block offset, output lane)
    _circuit_id: object = field(default=None, repr=False, compare=False)

    @property
    def a(self):
        """Reference to this multiplier's first input."""
        return _MulInput(mul_id=self.id, input_idx=0, _circuit_id=self._circuit_id)

    @property
    def b(self):
        """Reference to this multiplier's second input."""
        return _MulInput(mul_id=self.id, input_idx=1, _circuit_id=self._circuit_id)

    def source_output_lane(self) -> int:
        """Return the M-block output lane for this multiplier."""
        return self.lane

    def target_m_input(self) -> int:
        """Return the M-block input lane (defaults to a-input)."""
        return self.a.lane


@dataclass
class Identity:
    """
    Wrapper for an identity element (passthrough from M-block input to output).

    M-block inputs 8-11 (the multiplier inputs) are tapped to M-block
    outputs 12-15.  An identity element exposes this passthrough as a
    source in connections.  It coexists with multipliers and requires no
    allocation.

    Can only be used as a **source** in ``connect()``, not as a target.
    """

    offset: int  # 0-3, maps to M-block output 12+offset
    _circuit_id: object = field(default=None, repr=False, compare=False)

    def source_output_lane(self) -> int:
        """Return the M-block output lane for this identity element."""
        return 12 + self.offset


@dataclass
class Constant:
    """Wrapper for an allocated constant source.

    The constant giver is a single physical unit.  Its output appears on
    M-block output 15 (routable to lanes 0-15) and output 14 (routable to
    lanes 16-31).  The correct output is determined at connect() time based
    on which lane is allocated.
    """

    id: int  # allocation counter
    _circuit_id: object = field(default=None, repr=False, compare=False)


@dataclass
class Input:
    """Wrapper for an allocated ACL_IN port."""

    port: int  # 0-7, port number
    lane: int  # 24 + port
    _circuit_id: object = field(default=None, repr=False, compare=False)

    def source_output_lane(self) -> int:
        """Return the M-block output lane for this input."""
        return self.lane


@dataclass
class Output:
    """Wrapper for an allocated ACL_OUT port."""

    port: int  # 0-7, port number
    lane: int  # 24 + port
    _circuit_id: object = field(default=None, repr=False, compare=False)

    def target_m_input(self) -> int:
        """Return the M-block input lane for this output."""
        return self.lane


# Union type for element wrappers
Element = Union[Integrator, Multiplier, _MulInput, Identity, Constant, Input, Output]

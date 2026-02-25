# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

"""
Addressing validation and mapping utilities for the CLI DAC commands.

This module provides helper functions for handling physical/virtual address
mapping in configuration files before execution on REDAC hardware.
"""

import json
from typing import Callable

import pybrid.base.proto.main_pb2 as pb
from pybrid.base.utils.addressing import Addressing
from pybrid.redac.computer import REDAC
from pybrid.redac.sync import SyncImplementationType


def validate_and_map_config(
    pb_file: pb.File,
    strict: bool,
    portable_map_path: str | None,
    computer: REDAC,
    address_map: Callable,
) -> pb.File:
    """
    Validate and apply address mapping to a protobuf configuration file.

    If the file already has physical addresses, it is returned as-is.

    In strict mode, files with virtual addresses are rejected unless an
    explicit portable map is provided.

    In non-strict mode, either an explicit portable map is applied, or
    greedy auto-mapping is used (with a deprecation warning).

    Args:
        pb_file: Protobuf File with configuration to validate/map.
        strict: If True, reject virtual addresses unless portable_map_path is provided.
        portable_map_path: Optional path to a JSON file mapping virtual MACs to physical MACs.
        computer: REDAC computer object for auto-mapping.
        address_map: Callable that maps linear indices to virtual MAC addresses.

    Returns:
        The possibly-mapped protobuf File.

    Raises:
        ValueError: If strict=True and file has virtual addresses without a portable map.
        FileNotFoundError: If portable_map_path does not exist.
        json.JSONDecodeError: If portable_map_path is not valid JSON.
        Exception: If mapping encounters unmapped addresses.
    """
    # If file has physical addresses already, no mapping needed
    if Addressing.has_physical_addresses(pb_file):
        return pb_file

    # Explicit portable map takes precedence in both strict and non-strict modes
    if portable_map_path:
        with open(portable_map_path, "r") as f:
            mapping = json.load(f)
        return Addressing._map(pb_file, mapping)

    # Strict mode without portable map: reject virtual addresses
    if strict:
        raise ValueError(
            "Config file contains virtual addresses, which are rejected in strict mode. "
            "Use --portable-map to provide an explicit virtual-to-physical mapping, "
            "or use --no-strict to enable greedy auto-mapping (deprecated)."
        )

    # Non-strict fallback: greedy auto-mapping
    # The DeprecationWarning is emitted by Addressing.virtual_to_physical() itself.
    return Addressing.virtual_to_physical(computer, pb_file, address_map)


def parse_sync_impl(value: str) -> SyncImplementationType:
    """Map a CLI string to a SyncImplementationType enum member.

    Args:
        value: One of "native" or "usbspi".

    Returns:
        The corresponding SyncImplementationType enum member.

    Raises:
        ValueError: If the value is not a valid sync implementation type.
    """
    try:
        return SyncImplementationType(value)
    except ValueError:
        valid = ", ".join(e.value for e in SyncImplementationType)
        raise ValueError(
            f"Unknown sync implementation type '{value}'. Valid options: {valid}"
        )

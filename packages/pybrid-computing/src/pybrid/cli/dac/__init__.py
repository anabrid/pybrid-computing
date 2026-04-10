# Copyright (c) 2022-2024 anabrid GmbH
# Contact: https://www.anabrid.com/licensing/
# SPDX-License-Identifier: MIT OR GPL-2.0-or-later

import asyncio
import inspect
import json
import logging
import os
import sys
import typing
import math
from ipaddress import ip_network

import asyncclick as click
import matplotlib.pyplot as plt

import pybrid.base.proto.main_pb2 as pb
from pybrid.cli.base import cli
from pybrid.cli.base.commands import user_program
from pybrid.cli.dac.backend import expand_args, parse_backend_spec
from pybrid.lucidac.controller import Controller as LUCIDACController
from pybrid.redac.controller import Controller as REDACController
from pybrid.redac.data import DatExporter
from pybrid.redac.detect import detect_in_network
from pybrid.redac.display import TreeDisplay
from pybrid.mock import DummyDAC, DummyDACConfig, DummyDACMacMode
from pybrid.redac.run import Run, RunState, RunError
from pybrid.sim.controller import Controller as SimController
from pybrid.base.proto.io import ProtoIO

# controls logging verbosity - use for debugging
# logging.basicConfig(level=logging.INFO)

logger = logging.getLogger(__name__)

###
# Device initialization: LUCIDAC, REDAC, SIM prefixes
###

@cli.group()
@click.pass_context
@click.option(
    "--host",
    "-h",
    "hosts",
    type=str,
    required=False,
    multiple=True,
    help="Network name or address of the REDAC. Or address range to use for auto-detection.",
)
@click.option(
    "--port",
    "-p",
    type=int,
    default=5732,
    required=False,
    help="Network port of the REDAC.",
)
@click.option(
    "--reset/--no-reset",
    is_flag=True,
    default=True,
    show_default=True,
    help="Whether to reset the REDAC after connecting.",
)
async def redac(ctx: click.Context, hosts: list[str], port: int, reset: bool):
    """
    Entrypoint for all REDAC commands.

    Use :code:`pybrid redac --help` to list all available sub-commands.
    """
    bearer = os.getenv("PYBRID_AUTHENTICATION", None)
    if bearer is not None:
        logger.info("Using authentication bearer!")

    networks = []
    devices = []
    if not hosts:
        logger.warning(
            "Falling back to 0.0.0.0/0 zeroconf. Pass an explicit host or network with -h to silence this warning."
        )
        networks.append(ip_network("0.0.0.0/0"))
    for host in hosts:
        if "/" not in host:
            devices.append((host, port, str(host)))
        else:
            networks.append(ip_network(host))
    for network in networks:
        logger.info("Searching for available network devices in %s...", network)
        devices = await detect_in_network(network)
        logger.info("Found network devices at %s.", devices)

    controller = REDACController()
    for host, port, name in devices:
        await controller.add_device(host, port)

    ctx.obj["controller"] = controller
    await ctx.with_async_resource(controller)

    # Unless chosen otherwise, reset the analog computer
    if reset:
        await controller.reset()
    await asyncio.sleep(1)

    # Create a run which is potentially modified by other commands (e.g. set-readout-elements)
    run_class = controller.get_run_implementation()
    ctx.obj["run"] = run_class()
    ctx.obj["previous_run"] = None

@cli.group()
@click.pass_context
@click.option(
    "--host",
    "-h",
    type=str,
    default="localhost",
    required=False,
    help="Network name or address of the REDAC. Or address range to use for auto-detection.",
)
@click.option(
    "--port",
    "-p",
    type=int,
    default=5732,
    required=False,
    help="Network port of the REDAC.",
)
@click.option(
    "--entity",
    "-e",
    type=str,
    required=True,
    help="Path to entity definition, defining which hardware the simulator requires"
)
async def sim(ctx: click.Context, host: str, port: int, entity: str):
    """
    Entrypoint for all commands interacting with the simulator.

    Use :code:`pybrid redac --help` to list all available sub-commands.
    """
    bearer = os.getenv("PYBRID_AUTHENTICATION", None)
    if bearer is not None:
        logger.info("Using authentication bearer!")

    # Generate a controller and add devices
    controller = SimController()
    await controller.add_device(
        host, 
        port, 
        specification=ProtoIO.load_module(entity))

    # Put controller in context and make sure that we clean up after ourselves
    ctx.obj["controller"] = controller
    await ctx.with_async_resource(controller)

    # Create a run which is potentially modified by other commands (e.g. set-readout-elements)
    run_class = controller.get_run_implementation()
    ctx.obj["run"] = run_class()
    ctx.obj["previous_run"] = None

@cli.group()
@click.pass_context
@click.option(
    "--host",
    "-h",
    "hosts",
    type=str,
    required=False,
    multiple=True,
    help="Network name or address of the LUCIDAC. Or address range to use for auto-detection.",
)
@click.option(
    "--port",
    "-p",
    type=int,
    default=5732,
    required=False,
    help="Network port of the LUCIDAC.",
)
@click.option(
    "--reset/--no-reset",
    is_flag=True,
    default=False,
    show_default=True,
    help="Whether to reset the LUCIDAC after connecting.",
)
async def lucidac(ctx: click.Context, hosts: list[str], port: int, reset: bool):
    """
    Entrypoint for all LUCIDAC commands.

    Use :code:`pybrid lucidac --help` to list all available sub-commands.
    """
    networks = []
    devices = []
    if not hosts:
        logger.warning(
            "Falling back automatic LUCIDAC detection. Pass an explicit host or network with -h to silence this warning."
        )
        networks.append(ip_network("0.0.0.0/0"))
    for host in hosts:
        if "/" not in host:
            devices.append((host, port, str(host)))
        else:
            networks.append(ip_network(host))
    for network in networks:
        logger.info("Searching for available network devices in %s...", network)
        devices = await detect_in_network(network)
        logger.info("Found network devices at %s.", devices)

    controller = LUCIDACController()
    for host, port, device in devices:
        await controller.add_device(host, port)

    ctx.obj["controller"] = controller
    await ctx.with_async_resource(controller)

    if reset:
        await controller.reset()

    # Create a run which is potentially modified by other commands (e.g. set-readout-elements)
    run_class = controller.get_run_implementation()
    ctx.obj["run"] = run_class()
    ctx.obj["previous_run"] = None

###
# OPERATING functions: use devices select by the prefix above
###

@click.command()
@click.pass_obj
async def display(obj):
    """
    Display the hardware structure of the computer.
    """
    controller: REDACController = obj["controller"]
    click.echo(TreeDisplay().render(controller.computer))

@click.command()
@click.pass_obj
@click.option("--export", "-e", type=str, default=None, required=False, help="Export result to APB file")
@click.option("--specification/--no-specification", default=True, help="Include entity specifications.")
@click.option("--configuration/--no-configuration", default=False, help="Include entity configurations.")
@click.option("--calibration/--no-calibration", default=False, help="Include calibration data.")
@click.option("--skip-cache/--no-skip-cache", default=False, help="Force a fresh extract from the device.")
async def extract(obj, export: str, specification: bool, configuration: bool, calibration: bool, skip_cache: bool):
    """
    Extract device data (specification, configuration, calibration) and optionally store to file.
    """
    controller: REDACController = obj["controller"]

    if skip_cache or configuration or calibration:
        module = pb.Module(items=[])
        for conn in controller.connection_manager.get_unique_connections():
            result = await conn.control.extract(
                specification=specification,
                configuration=configuration,
                calibration=calibration,
            )
            module.items.extend(result.items)
    else:
        module = await controller.extract()

    # if no location data is given, inject a linear order of carriers
    carrier_ix = 0
    for item in module.items:
        if item.HasField("entity_specification"):
            entity = item.entity_specification.entity
            if not entity.HasField("location_v0"):
                entity.location_v0.CopyFrom(pb.CarrierLocationV0(stack=0, carrier=carrier_ix))
                carrier_ix += 1

    if export:
        if export.endswith(".apb"):
            ProtoIO.store_module(module, export)
        else:
            click.echo("Unknown file format, only .apb is supported.")
    else:
        print(module)


@click.command()
@click.pass_obj
@click.option("--keep-calibration", type=bool, default=True, help="Whether to keep calibration.")
@click.option(
    "--sync/--no-sync",
    default=True,
    help="Whether to immediately sync configuration to hardware.",
)
async def reset(obj, keep_calibration, sync):
    """
    Reset the computer to initial configuration.
    """
    controller: REDACController = obj["controller"]
    await controller.reset(keep_calibration=keep_calibration, sync=sync)

@click.command()
@click.pass_obj
# Run options
@click.option("--op-time", type=float, default=None, help="OP time in seconds.")
@click.option("--sample-rate", type=int, default=None, help="Sample rate in Hz.")
@click.option("--ic-time", type=int, default=None, help="IC time in nanoseconds.")
# Configuration options
@click.option("--config-file", "-c", type=str, help="Path to a config (.apb) file to set up the device and start the run.")
# Output options
@click.option("--output", "-o", type=click.File("wt"), default="-", help="File to write data to.")
@click.option("--plot", 
    is_flag=True,
    default=False,
    show_default=True,
    help="Use matplotlib to draw a simple plot of the returned data")
async def run(obj, op_time: float, sample_rate: int, ic_time, config_file: str, output, plot):
    """
    Start a run (computation) and wait until it is complete. Wires the configuration
    to the device in RAW form, i.e. the user is responsible for its correctness.
    """
    controller: REDACController = obj["controller"]
    run_: Run = obj["run"]

    # load config and update to most recent version (if provided)
    # Build a single session for config + run
    session = controller.create_session()

    if config_file is not None:
        pb_module = ProtoIO.load_module(config_file)
        session.set_module(pb_module)
    else:
        logger.warning("No config file provided, device will replay the last configuration...")

    # If the run in the context object is already done, we need a new one
    if run_.state.is_done():
        run_ = Run.make_from_other_run(run_)

    # Set run config
    if ic_time is not None:
        run_.config.ic_time = ic_time
    if op_time is not None:
        # needs to be set in nanoseconds
        run_.config.op_time = math.ceil(op_time * 1_000_000_000)
    if sample_rate is not None:
        run_.daq.sample_rate = sample_rate

    effective_op_time = op_time if op_time is not None else run_.config.op_time / 1_000_000_000
    timeout = max(effective_op_time + 3, 3)
    session.calibrate()
    session.run(run_.config, daq=run_.daq, timeout=timeout)
    results = await session.execute()
    if results:
        run_ = results[0]
    obj["run"] = run_
    if run_.state is RunState.ERROR:
        raise RunError("Error while executing run.")

    if output is not None:
        exporter = DatExporter(output)
        exporter.export(run_)

    # Plot data if requested
    if plot:
        if run_.data:
            plt.figure(figsize=(10, 6))
            for channel_ix, channel_data in enumerate(run_.data):
                plt.plot(channel_data, label=str(channel_ix))
            plt.xlabel('Sample Index')
            plt.ylabel('Value')
            plt.title('Run Data')
            plt.legend()
            plt.grid(True)
            plt.show()
        else:
            click.echo("No data available to plot.")

@cli.command()
@click.pass_obj
@click.argument(
    "filename",
    type=str,
    default="report.pdf")
async def report(obj, filename: str):
    """
    Create a calibration report for an attached device and export as PDF.
    """
    controller: REDACController | LUCIDACController = obj["controller"]
    
    from pybrid.util.reporter import Reporter, sin_test, mul_test, lane_test, itor_test

    reporter = Reporter(output=filename)
    reporter.drawString("Device Report", 24)
    async with controller:
        await sin_test(controller, reporter)
        await lane_test(controller, reporter)
        await mul_test(controller, reporter)
        await itor_test(controller, reporter)
    reporter.save()
    
@cli.command("read-apb")
@click.argument(
    "filename",
    type=str
)
async def read_apb(filename: str):
    """Converts an APB file into human-readable JSON for debugging purposes."""
    apb = ProtoIO.load_module(filename, skip_update=True)
    print(apb)

@cli.command("reset-usb")
@click.option(
    "--filter",
    "-f",
    "tag_filter",
    type=str,
    default="Teensy",
    show_default=True,
    help="Only reset boards whose tag contains this string.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="List matching boards without resetting them.",
)
async def reset_usb(tag_filter: str, dry_run: bool):
    """
    Hardware-reset USB-connected Teensy boards via tycmd.

    Enumerates all boards known to tycmd, filters by tag, and issues
    a reset for each match. Requires tycmd to be installed and on PATH.
    """
    import shutil
    import subprocess

    tycmd = shutil.which("tycmd")
    if tycmd is None:
        click.echo("Error: tycmd not found on PATH.", err=True)
        raise SystemExit(1)

    result = subprocess.run(
        [tycmd, "list", "--output", "json"],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode != 0:
        click.echo(f"Error: tycmd list failed: {result.stderr.strip()}", err=True)
        raise SystemExit(1)

    boards = json.loads(result.stdout) if result.stdout.strip() else []
    matches = [b for b in boards if tag_filter in b.get("tag", "")]

    if not matches:
        click.echo(f"No boards matching '{tag_filter}' found.")
        return

    for board in matches:
        tag = board["tag"]
        if dry_run:
            click.echo(f"[dry-run] Would reset: {tag}")
        else:
            click.echo(f"Resetting {tag}...")
            r = subprocess.run(
                [tycmd, "reset", "--board", tag],
                capture_output=True, text=True, timeout=10,
            )
            if r.returncode != 0:
                click.echo(f"  Warning: reset failed for {tag}: {r.stderr.strip()}", err=True)
            else:
                click.echo(f"  Done.")

    if not dry_run:
        click.echo(f"Reset {len(matches)} board(s).")

@click.command()
@click.argument("firmware", type=str)
@click.pass_obj
async def update(obj, firmware: str):
    """
    OTA update for a device (real device, not simulator).
    """
    controller: REDACController | LUCIDACController = obj["controller"]

    # create a session that _only_ updates the firmware
    session = controller.create_session()
    session.set_firmware(firmware, verbose=True)
    await session.execute()

@cli.command()
@click.argument("host", type=str)
@click.option("--port", "-p", type=int, default=5732)
@click.option("--timeout", "-t", type=float, default=3.0)
@click.option("--count", "-c", type=int, default=1, help="Number of pings to send.")
async def ping(host: str, port: int, timeout: float, count: int):
    """Send a V1 PingCommand to a device and measure round-trip time."""
    try:
        from pybrid.native import ControlChannel
    except ImportError:
        click.echo("Error: Native C++ extension not available.", err=True)
        raise SystemExit(1)

    import time

    cc = ControlChannel.create(host, port, timeout)
    cc.start()

    try:
        for i in range(count):
            t0 = time.monotonic()
            try:
                cc.ping(timeout)
                elapsed = (time.monotonic() - t0) * 1000
                click.echo(f"Reply from {host}:{port}: time={elapsed:.1f}ms")
            except Exception as e:
                click.echo(f"Ping {host}:{port} failed: {e}")
    finally:
        cc.stop()

@cli.command()
@click.pass_obj
async def detect(obj):
    """
    Detect devices in local network.
    """
    print("Detecting network devices...")
    for (host, port, name) in await detect_in_network(ip_network("0.0.0.0/0")):
        print(f"{host:15}:{port:4} {name}")

@cli.command()
@click.option(
    "--listen",
    "-l",
    type=str,
    default="0.0.0.0",
    show_default=True,
    help="Local bind address for the proxy server.",
)
@click.option(
    "--port",
    "-p",
    type=int,
    default=5732,
    show_default=True,
    help="Local port for the proxy server.",
)
@click.option(
    "--backend",
    "-b",
    type=str,
    multiple=True,
    required=True,
    help="Backend device address(es) in HOST[:PORT][/STACK/CARRIER] format. Accepts a single spec, a comma-separated list, or a path to a file with one spec per line. Can be specified multiple times.",
)
@click.option(
    "--session-timeout",
    type=float,
    default=10.0,
    show_default=True,
    help="Session idle timeout in seconds after a run completes.",
)
@click.option(
    "--auth/--no-auth",
    default=False,
    show_default=True,
    help="Enable proxy-level authentication (reads PYBRID_AUTHENTICATION env var).",
)
@click.option(
    "--debug",
    is_flag=True,
    default=False,
    show_default=True,
    help="Enable verbose debug logging (session lifecycle, run events, errors).",
)
async def proxy(listen: str, port: int, backend: tuple[str, ...], session_timeout: float, auth: bool, debug: bool):
    """
    Start a native C++ proxy server in front of one or more LUCIDAC devices.

    Clients connect to the proxy on LISTEN:PORT and are transparently
    forwarded to the backend devices. The proxy handles session management,
    describe caching, and multi-backend routing.

    Example usage:

        pybrid proxy -b 192.168.150.57 -b 192.168.150.58
        pybrid proxy -b 192.168.150.57/0/0,192.168.150.58/0/1
        pybrid proxy -b /path/to/backends.txt
        pybrid proxy -b 192.168.150.57:5732/0/0 -l 0.0.0.0 -p 5732
        pybrid proxy -b 192.168.150.57 --auth
    """
    try:
        from pybrid.native import ProxyServer
    except ImportError:
        click.echo("Error: Native C++ extension not available. Build pybrid-computing-native first.", err=True)
        raise SystemExit(1)

    raw_backends = expand_args(backend)
    if not raw_backends:
        click.echo("Error: No backend addresses resolved from the provided -b values.", err=True)
        raise SystemExit(1)

    specs = [parse_backend_spec(raw) for raw in raw_backends]

    has_any_location = any(s.stack is not None for s in specs)
    if not has_any_location:
        click.echo("Warning: Without REDAC addresses, all carriers will be treated equal. For LUCIDACs, you can safely ignore this warning. When using a REDAC, this means that pybrid will not be able to route signals automatically.")

    proxy_server = ProxyServer(auth)
    if debug:
        proxy_server.set_debug(True)

    for spec in specs:
        click.echo(f"Connecting to backend {spec.host}:{spec.port}...")
        proxy_server.add_backend(spec.host, spec.port, stack=spec.stack, carrier=spec.carrier)
    proxy_server.map_backends()

    proxy_server.set_session_timeout(session_timeout)
    proxy_server.start(listen, port)

    actual_port = proxy_server.local_port()
    click.echo(f"Proxy server listening on {listen}:{actual_port}")
    click.echo(f"Backends: {len(specs)}, session timeout: {session_timeout}s")
    click.echo("Press Ctrl+C to stop.")

    try:
        while proxy_server.is_running():
            await asyncio.sleep(0.5)
    except (KeyboardInterrupt, asyncio.CancelledError):
        click.echo("\nShutting down proxy server...")
    finally:
        proxy_server.stop()
        click.echo("Proxy server stopped.")


@cli.command()
@click.option(
    "--host",
    "-h",
    type=str,
    default="0.0.0.0",
    show_default=True,
    help="Host address to bind the DummyDAC server to.",
)
@click.option(
    "--port",
    "-p",
    type=int,
    default=5732,
    show_default=True,
    help="Port to bind the DummyDAC server to.",
)
@click.option(
    "--virtual/--physical",
    default=True,
    show_default=True,
    help="Use virtual MACs (00-00-00-00-00-XX) or random physical MACs.",
)
async def dummy(host: str, port: int, virtual: bool):
    """
    Start a DummyDAC mock server for testing purposes.

    The DummyDAC simulates REDAC hardware and can be used for testing
    without physical hardware. It responds to the same protocol as
    real hardware.

    Example usage:

        pybrid dummy -h 0.0.0.0 -p 5732
        pybrid dummy --physical  # Use random MAC addresses
    """
    mac_mode = DummyDACMacMode.VIRTUAL if virtual else DummyDACMacMode.PHYSICAL
    config = DummyDACConfig(mac_mode=mac_mode)

    addr_method = "virtual" if virtual else "physical"
    click.echo(f"Starting DummyDAC server on {host}:{port} using {addr_method} addressing...")
    click.echo("Press Ctrl+C to stop.")

    async with DummyDAC(host, port, config) as server:
        # Keep the server running until interrupted
        try:
            while True:
                await asyncio.sleep(1)
        except (KeyboardInterrupt, asyncio.CancelledError):
            click.echo("\nShutting down DummyDAC server...")


###
# add all commands in this file to both groups (LUCIDAC, REDAC)
###

current_module = sys.modules[__name__]

for name, obj in inspect.getmembers(current_module):
    # Check if it's a Click command (has __click_params__ attribute)
    if hasattr(obj, 'callback') and hasattr(obj, 'params'):
        # Skip if it's a group (groups are also commands but we don't want them)
        if isinstance(obj, click.Group):
            continue

        # Skip top-level commands (already registered with cli group)
        if name in ['detect', 'dummy', 'proxy', 'reset_usb']:
            continue

        # Add the command to both groups
        redac.add_command(obj)
        lucidac.add_command(obj)
        sim.add_command(obj)

# add imported commands
redac.add_command(user_program)
lucidac.add_command(user_program)
sim.add_command(user_program)

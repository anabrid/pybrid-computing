# Using the CLI

`pybrid` ships with a command-line tool, also called `pybrid`, that
covers device discovery, calibration, firmware updates, and running
precompiled circuits without writing a line of Python.

Every command, sub-group, and option is documented in place via
`--help`, which works at the top level as well as on any sub-group
(`lucidac`, `redac`, `sim`) or individual command. We use it
throughout this page to surface options without having to memorise
them. Running

```bash
uv run pybrid --help
```

prints the top-level summary, which looks like this:

```
Usage: pybrid [OPTIONS] COMMAND [ARGS]...

  Entrypoint for all functions in the pybrid command line tool.

Options:
  --log-level [CRITICAL|ERROR|WARNING|INFO|DEBUG]
                                  Set all 'pybrid' loggers to the passed
                                  level.
  --help                          Show this message and exit.

Commands:
  detect     Detect devices in local network.
  dummy      Start a DummyDAC mock server for testing purposes.
  lucidac    Entrypoint for all LUCIDAC commands.
  ping       Send a V1 PingCommand to a device and measure round-trip time.
  proxy      Start a native C++ proxy server in front of one or more...
  read-apb   Converts an APB file into human-readable JSON for debugging...
  redac      Entrypoint for all REDAC commands.
  report     Create a calibration report for an attached device and...
  reset-usb  Hardware-reset USB-connected Teensy boards via tycmd.
  sim        Entrypoint for all commands interacting with the simulator.
```

## Direct commands and device-prefixed commands

Commands split into two groups depending on whether they need an
active connection to an analog device.

- **Direct commands** operate either at the network level or on local
  files and do not need a device to be connected first. `detect`,
  `proxy`, `ping`, `dummy`, `reset-usb`, and `read-apb` are all
  invoked as `pybrid <command> ...`.
- **Device-prefixed commands** first open a connection through a
  device group (`lucidac`, `redac`, or `sim`) and then execute an
  operation against that device. They run as
  `pybrid <prefix> <command> ...`, and the prefix configures host,
  port, and reset behaviour for the opened connection.

The three device groups accept a shared set of options (host, port,
whether to reset on connect). The full list of sub-commands available
under a given prefix is, again, one `--help` away:

```bash
uv run pybrid lucidac --help
uv run pybrid redac --help
uv run pybrid sim --help
```

Typical invocations therefore look like:

```bash
uv run pybrid lucidac -h 192.168.1.2 run -c my-circuit.apb --plot
uv run pybrid redac -h 192.168.110.91 extract -e redac.apb
```

In the examples below we omit `-h` / `-p` wherever the choice of host
is unrelated to the point being made; supply them in practice as
shown above.

## Workflow commands

### `detect`: discover devices on the network

`detect` uses mDNS/zeroconf to find all active LUCIDAC/mREDAC devices
on the local network and prints their IP address, control port, and
mDNS service name. It needs no arguments:

```bash
uv run pybrid detect
```

See [Identifying your device](../getting-started/identifying-your-device.md)
for a walkthrough of the output and guidance on matching the
advertised hostnames against the physical device labels.

### `ping`: verify a device is alive and responsive

`ping` is *not* a network-layer ICMP ping. It opens a control channel
to the device and sends a `PingCommand` protobuf message, then
measures the round-trip time of the reply:

```bash
uv run pybrid ping 192.168.1.2
```

Because the message is handled by the firmware rather than by the
operating-system network stack, a successful `ping` is strong
evidence that the firmware is running, responsive, and speaking the
expected protocol version. A missed `ping` despite a reachable IP
therefore points at a firmware problem (or a protocol-version
mismatch) rather than at a network problem.

Useful options:

- `--port` / `-p` sets the control port (default `5732`).
- `--timeout` / `-t` sets the per-request timeout in seconds
  (default `3.0`).
- `--count` / `-c` sends multiple pings in a row, e.g. `-c 5`, to
  get a feel for jitter and packet loss.

### `<prefix> display`: show the device's entity hierarchy

`display` asks the connected device for its hardware specification
and prints it as a tree, starting at the carrier and descending
through clusters and blocks down to individual elements. There are no
options: the command is a quick human-readable sanity check of what
`pybrid` actually sees on the wire.

```bash
uv run pybrid lucidac -h 192.168.1.2 display
```

Reach for `display` whenever a circuit does not behave as expected
and you want to confirm that the device presents the blocks and
elements you think it does. For a machine-readable dump (or for
feeding the structure into the simulator), use
[`extract`](#prefix-extract-pull-the-entity-specification) instead.

### `<prefix> extract`: pull the entity specification

`extract` reads the hardware structure (and optionally its current
configuration and calibration data) off a connected device and
either prints it or stores it to disk. The most common use is
grabbing the entity specification of a device so that the
[simulator](./programmatically.md) or an offline tool can work with
the same hardware shape:

```bash
uv run pybrid lucidac -h 192.168.1.2 extract -e lucidac-spec.apb
```

Useful options:

- `--export` / `-e PATH` writes the result to an `.apb` file
  (see [File formats](./file-formats.md)); without it, the extracted
  module is printed to stdout as text-format protobuf.
- `--specification/--no-specification` (default on),
  `--configuration/--no-configuration` (default off), and
  `--calibration/--no-calibration` (default off) choose which parts
  of the device state to include.
- `--skip-cache` forces a fresh extraction from the device and
  bypasses the cached specification the controller holds in memory.

### `<prefix> run`: execute a circuit and collect results

`run` executes a circuit on the device and either prints the
captured data to stdout, writes it to a file, or plots it with
`matplotlib`. It is particularly handy for running circuits
generated by anabrid's `redacc` compiler: the compiler emits an
`.apb` file describing the full configuration, and `run -c <file>`
sends it to the device and executes it in one step.

```bash
uv run pybrid lucidac -h 192.168.1.2 run \
    -c compiled.apb \
    --op-time 0.002 \
    --sample-rate 100000 \
    -o samples.dat \
    --plot
```

Useful options:

- `--config-file` / `-c PATH` loads an `.apb` file and sends it as
  the device configuration before starting the run. If omitted,
  `pybrid` warns and the device re-runs whatever configuration was
  loaded last.
- `--op-time SECONDS` sets the OP duration (integration time); the
  CLI accepts seconds and converts internally to the nanosecond
  precision the device expects.
- `--sample-rate HZ` sets the target sample rate on the DAQ.
- `--ic-time NANOSECONDS` sets the initial-condition phase duration.
- `--output` / `-o FILE` writes captured samples as `.dat`
  (tab-separated, one column per channel) to the given path; pass
  `-` for stdout.
- `--plot` additionally opens a `matplotlib` window with one line
  per captured channel.

### `proxy`: run a transparent proxy

`proxy` starts the native C++ proxy in front of one or more devices.
It is documented in full on its own page, including backend-list
formats, session handling, and how to keep it running as a `systemd`
user service:

```bash
uv run pybrid proxy -b /path/to/backends.txt
```

See [Proxy](./proxy.md) for the details.

## Maintenance commands

These commands are not part of the day-to-day configure-run-evaluate
loop but come up when a device misbehaves or needs to be brought to
a new firmware release.

### `<prefix> report`: generate a calibration report

`report` runs a canned sequence of characterisation tests (sinusoid,
lanes, multipliers, integrators) against the connected device and
writes a PDF summarising the results:

```bash
uv run pybrid lucidac -h 192.168.1.2 report my-device.pdf
```

The file name is a positional argument and defaults to `report.pdf`
if omitted. This PDF is the standard artefact to attach when
corresponding with anabrid about suspected hardware failures: it
contains the measurements we need to reason about the state of the
analog core without having access to the device.

### `<prefix> update`: OTA firmware update

`update` pushes a new firmware image to the device over the same
control channel that is used for configuration. The image path is a
positional argument:

```bash
uv run pybrid lucidac -h 192.168.1.2 update lucidac-firmware-x.y.z.bin
```

Firmware images for the LUCIDAC are distributed through the
[lucidac-resources](https://github.com/anabrid/lucidac-resources)
repository. The command only works against real hardware, not
against the simulator. After a successful update the device reboots,
so re-open the connection with a fresh `pybrid` invocation before
sending more commands.

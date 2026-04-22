# Identifying Your Device

All anabrid devices of the LUCIDAC/REDAC family communicate over
ethernet, and this is the primary transport `pybrid` uses to talk to
your hardware. Before running a circuit, we first need to know the IP
address at which your device is reachable.

## Device types

The LUCIDAC and the mREDAC are each a single physical device reached
at a single IP address, and the detection procedure described on this
page applies to both. An iREDAC, by contrast, bundles several mREDACs,
each with its own IP address, and is typically operated behind a
[proxy](../using-pybrid/proxy.md) that fronts all of them under a
single endpoint. Setting up an iREDAC is out of scope for this guide;
please refer to the setup guide shipped with your device. The
remainder of this page covers the detection procedure for a LUCIDAC or
a single mREDAC.

We make two assumptions throughout: that your device is connected to
the same network as your client PC, and that a DHCP server is running
on that network and has assigned an IP address to the device.

## Detecting devices via the CLI

`pybrid` ships with an integrated command-line tool that we use for
device discovery. Running it with `--help` shows the available
top-level subcommands:

```bash
uv run pybrid --help
```

The output looks roughly like this, though the exact list of commands
depends on which `pybrid-computing-*` packages you have installed:

```
Usage: pybrid [OPTIONS] COMMAND [ARGS]...

  Entrypoint for all functions in the pybrid command line tool.

  Additional :code:`pybrid-computing` packages hook new subcommands into this
  entrypoint. Please see their documentation for additional available
  commands.

Options:
  --log-level [CRITICAL|ERROR|WARNING|INFO|DEBUG]
                                  Set all 'pybrid' loggers to the passed
                                  level.
  --help                          Show this message and exit.

Commands:
  detect     Detect devices in local network.
  dummy      Start a DummyDAC mock server for testing purposes.
  lucidac    Entrypoint for all LUCIDAC commands.
  proxy      Start a native C++ proxy server in front of one or more...
  redac      Entrypoint for all REDAC commands.
  reset-usb  Hardware-reset USB-connected Teensy boards via tycmd.
  sim        Entrypoint for all commands interacting with the simulator.
```

The subcommand we need here is `detect`, which discovers all active
LUCIDAC/mREDAC devices reachable in the local network via mDNS/zeroconf:

```bash
uv run pybrid detect
```

A typical run on a lab network with four devices prints their IP
address, control port, and mDNS service name:

```
192.168.150.57 :5732 lucidac-17-E5-68._lucijsonl._tcp.local.
192.168.150.15 :5732 lucidac-17-E5-66._lucijsonl._tcp.local.
192.168.150.69 :5732 lucidac-18-16-43._lucijsonl._tcp.local.
192.168.150.17 :5732 lucidac-15-87-A0._lucijsonl._tcp.local.
```

## Picking your device from the output

Every device in the LUCIDAC/REDAC family advertises itself with a
hostname of the form `lucidac-XX-YY-ZZ`, where `XX-YY-ZZ` are the last
six hex digits of the MAC address printed on the device's label. When
several devices are visible at once, match the hostname against the
label on the physical device to pick the one you want, and note its
IP address (and the `5732` control port) for later use with `pybrid`.

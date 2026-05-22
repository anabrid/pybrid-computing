# Proxy

The "proxy" functionality covers a class of (digital) devices that sit
between a client and an analog device and act as an invisible relay.
Once set up, users connect to the proxy exactly as they would to the
device itself: protocol-wise the proxy is fully transparent, and no
code on the client side needs to change. The rule of thumb for when
to reach for a proxy is: whenever you are not directly connected to
the analog computer, or at least not in the same ethernet-based local
network as the device.

## Functionality of the proxy

There are two main reasons to put a proxy in front of your analog
devices.

**Session management.** The firmware on LUCIDAC and REDAC devices is
kept deliberately simple in favor of performance: in particular, it
has no notion of multiple connections and will treat every incoming
message the same way, regardless of sender. If two users (or two
scripts) connect to the same device at the same time, their commands
interleave and interfere with each other. The proxy solves this by
introducing the concept of a `ClientSession`: while a session is
active, the proxy reserves the backend for that client and holds back
traffic from other clients until the session is released. The session
is released automatically after a configurable idle timeout (10
seconds by default, see `--session-timeout` below), so a client that
crashes does not lock up the device indefinitely.

**Sample buffering.** Devices have a sample buffer of limited size
that fills up faster the higher the sample rate is. Since samples are
streamed back to the client over the network, the network's latency
and throughput effectively cap the sustainable sample rate. If the
client cannot drain the buffer quickly enough, the device produces a
`DMA overflow` error and aborts the run. The full per-device rate
(around 500 kHz per mREDAC/LUCIDAC) therefore requires a full-speed,
low-latency 100 Mbit/s connection to the client. A proxy placed on
the local network next to the device can drain the buffer at line
rate on behalf of a slower or more distant client, buffer the
samples, and then forward them to the client over whatever connection
is available. The client sees the full sample rate even when the path
from client to proxy would not be able to sustain it on its own.

## How to use the proxy

`pybrid-computing-native` ships with a ready-to-use proxy that is
invoked through the `pybrid` CLI. The client side needs no special
configuration: the proxy speaks the same wire protocol as the device,
so all existing scripts, the [lucipy syntax](./lucipy.md), and
[`LUCIStack`](./programmatically.md) simply point at the proxy's
address instead of the device's.

### Starting the proxy from the CLI

The minimal invocation takes one or more backend addresses via `-b`
and starts listening on `0.0.0.0:5732`:

```bash
uv run pybrid proxy -b 192.168.150.57 -b 192.168.150.58
```

Each `-b` value describes one backend, and the flag can be repeated
for multi-device setups. The listen address and port are configurable
via `--listen` and `--port`:

```bash
uv run pybrid proxy \
    -b 192.168.150.57 \
    --listen 0.0.0.0 \
    --port 5732
```

Further options control behaviour rather than topology:

- `--session-timeout` (seconds, default `10.0`) sets how long a
  session may stay idle, that is, receive no traffic at all, before
  it is released to the next client.
- `--auth` / `--no-auth` enables proxy-level authentication; when on,
  the shared secret is read from the `PYBRID_AUTHENTICATION`
  environment variable.
- `--debug` turns on verbose logging of session lifecycle events,
  run transitions, and errors. Useful for troubleshooting, noisy in
  production.

### Backend specification format

For anything beyond a single device, spelling out every backend on
the command line every time quickly gets tedious and error-prone. We
therefore recommend keeping the list of backends in a plain text file
and passing that file's path to `-b`: the file can be
version-controlled, commented, and reused across invocations, so your
lab topology is described in one place. Canonical examples live under
`examples/proxy/` in the repository and are the basis for the
snippets in the following section.

!!! info "Pin device IP addresses on the DHCP side"

    The entries in a backend file reference each device by IP or
    hostname, so every time DHCP hands one of your devices a new
    lease the file needs updating. To avoid this, pin each device's
    address on the DHCP server (a static reservation keyed on the
    device's MAC). Once done, the backend file effectively becomes a
    permanent description of your setup.

A backend file is a sequence of directives, one per line. Blank lines
and lines beginning with `#` are ignored. Two directives are
recognised:

- `carrier <host>[:port] [[stack/]carrier]` declares one device. The
  port defaults to `5732`. The optional location is either a bare
  carrier index (LUCIStack) or `stack/carrier` (REDAC); it must be
  present and consistent across all `carrier` lines that take part
  in a `wire`.

```
carrier 192.168.150.57 0
carrier lucidac-AA-BB-CC:5732 1
carrier 192.168.110.91 0/0
```

- `wire <src> <dst>` declares a directed ACL connection between two
  carriers. Each endpoint is `<carrier>/<pin>` (when carriers are
  not stacked) or `<stack>/<carrier>/<pin>` (when they are). The
  `<pin>` position accepts either an integer index `0..7` (referring
  to ACL_OUT on the source side and ACL_IN on the target side) or
  one of the named pins `aux0`, `aux1`, `gen0`, `gen1`. See
  [Wiring LUCIDACs together (ACL I/O)](#wiring-lucidacs-together-acl-io)
  below for the semantics.

```
wire 0/4 1/4
wire 1/4 0/4
wire 0/aux0 0/3
```

`examples/proxy/list-lucistack-bernd.txt` is the canonical example
combining both directives for a two-LUCIDAC stack.

!!! info "Legacy syntax still accepted"

    Earlier versions of `pybrid` used a positional syntax that is
    still supported for backwards compatibility:

    - Bare `HOST[:PORT]` lines (LUCIDAC).
    - `HOST[:PORT]/STACK/CARRIER` lines (REDAC).
    - The same forms inline, e.g. `-b 192.168.150.57` or
      `-b 192.168.150.57/0/0,192.168.150.58/0/1`.

    The `wire` directive is not available in legacy form; files
    that need ACL wiring must use the keyword syntax above. Mixing
    keyword and legacy `carrier` entries in the same file works but
    we recommend committing to one style per file.

### Choosing between LUCIDAC and REDAC backend lists

The decision between the two list styles is driven entirely by which
hardware sits behind the proxy.

A proxy in front of one or more **LUCIDACs** (each of which is a
single, self-contained device) lists each carrier without a stack.
A standalone LUCIDAC only needs a `carrier` line; the carrier index
is required as soon as `wire` directives reference it. A
single-device list (`examples/proxy/list-lucidac-daniel.txt`) is as
short as it gets:

```
carrier 192.168.150.17
```

Multiple LUCIDACs behind the same proxy (a "LUCIStack") get one
`carrier` line each plus optional `wire` directives describing the
analog interconnect; `examples/proxy/list-lucistack-bernd.txt`
shows both:

```
carrier 192.168.150.57 0
carrier 192.168.150.17 1

wire 0/4 1/4
wire 1/4 0/4
```

A proxy in front of a **REDAC**, by contrast, must carry location
information for each mREDAC. A REDAC is assembled from one or more
iREDACs, where each iREDAC is itself a physical stack that groups
several mREDACs. `pybrid` needs the `stack/carrier` pair to route
signals between mREDACs correctly: the `stack` index identifies the
iREDAC, and the `carrier` index identifies the mREDAC within that
iREDAC. A single mREDAC is therefore written with an explicit
location even when no other mREDACs are present:

```
carrier 192.168.150.69 0/0
```

A full iREDAC is a contiguous block of `carrier` entries sharing the
same `stack` index, with `carrier` indices running from `0` upwards,
one per mREDAC in the stack. The MAC addresses in the `#`-comments
make it easy to cross-check the list against the device labels:

```
# 04-E9-E5-17-E5-67
carrier 192.168.110.91 0/0

# 04-E9-E5-18-14-88
carrier 192.168.110.98 0/1

# ... five more carriers at 0/2 through 0/6 ...
```

A full REDAC assembly is then several such blocks on top of each
other, one per iREDAC, with `stack` indices `0`, `1`, `2`, ... and
`carrier` indices restarting from `0` inside each iREDAC.

!!! warning "Missing location information on REDAC backends"

    If you pass bare host entries for a REDAC, `pybrid` issues a
    warning along the lines of _"Without REDAC addresses, all
    carriers will be treated equal"_ and will not be able to route
    signals automatically between carriers. The warning is safe to
    ignore for pure LUCIDAC setups but indicates a broken
    configuration for a REDAC.

### Wiring LUCIDACs together (ACL I/O)

Each LUCIDAC exposes 8 ACL_IN and 8 ACL_OUT pins (mapped to lanes
24–31 on the internal cross-bar). In a LUCIStack these pins form the
analog interconnect between the individual carriers: an ACL_OUT on
one device is patched to an ACL_IN on another with a flat-band cable.
The proxy needs to know about every patched signal so it can present
the multi-device assembly as a single computer with correctly routed
analog flow.

- A `wire <src> <dst>` directive declares one directed signal. The
  source endpoint is always an ACL_OUT pin, the target endpoint
  always an ACL_IN pin. Pin indices are `0..7`. Alternatively, the
  `<pin>` position may be one of the named pins `aux0`, `aux1`,
  `gen0`, `gen1`. A directive may mix named and indexed endpoints
  (e.g. `wire 0/aux0 0/3` patches `aux0` on carrier `0` to indexed
  pin `3` on the same carrier).
- Each endpoint identifies a carrier by the location given on its
  `carrier` line: `<carrier>/<pin>` when the file uses bare carrier
  indices, `<stack>/<carrier>/<pin>` when the file uses
  `stack/carrier` locations. Source and target must use the same
  form; a wire cannot bridge a stacked and an unstacked carrier.
- A physical patch cable carries one direction only; bidirectional
  links need two `wire` lines, one per direction. The wiring block
  in `examples/proxy/list-lucistack-bernd.txt` shows the symmetric
  4-pin pairing typical of a two-LUCIDAC stack:

```
# I/O wiring between systems (coordinates: stack / carrier / pin)
wire 0/4 1/4
wire 0/5 1/5
wire 0/6 1/6
wire 0/7 1/7
wire 1/4 0/4
wire 1/5 0/5
wire 1/6 0/6
wire 1/7 0/7
```

- At proxy start every `wire` is materialised as a top-level
  `WiringSpecification` item (empty entity id) in the cached spec, so
  clients pick the wiring up through the regular extract path with no
  client-side configuration needed.

On the circuit side, ACL_IN and ACL_OUT are allocated through the
usual lucipy helpers; see the [lucipy syntax](./lucipy.md) page for
how those ports are referenced from inside a `Circuit`.

### Running the proxy as a systemd user service

!!! info "Linux-only section"

    The instructions below apply to Linux hosts running `systemd` as
    their init system (which covers essentially all current desktop
    and server distributions). Running the proxy as a background
    service on Windows or macOS is out of scope for this guide;
    please use the native service mechanisms of those platforms or
    a lightweight process supervisor of your choice.

On a lab machine the proxy is typically something you want to start
once and forget about. Running it as a systemd _user_ service
(so no root privileges are needed) fits this usage well. The service
definition lives under `~/.config/systemd/user/` and references the
`pybrid` entry point and the backend list by absolute path.

Before going further, check that your distribution ships `systemd`
and that a user instance is available for your account. A quick
round-trip through the two standard commands confirms both:

```bash
# prints the systemd version (exit code 0 on any systemd system)
systemctl --version

# lists services running under your user manager; any output, or an
# empty list without an error, means the user instance is available
systemctl --user list-units --type=service
```

If the first command is missing, your host does not run `systemd` and
the rest of this section does not apply. If the second command errors
out with something like _"Failed to connect to bus"_, your login
session is not attached to a user manager; logging out and back in, or
starting a fresh `systemd --user` instance via your display manager,
usually resolves it.

A minimal unit file at
`~/.config/systemd/user/pybrid-proxy.service` looks like this:

```ini
[Unit]
Description=pybrid proxy for LUCIDAC/REDAC
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/home/USER/.venvs/pybrid/bin/pybrid proxy -b /home/USER/pybrid/backends.txt
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```

Replace `USER` and the two paths with the location of your virtual
environment and your backend list. After editing the unit, reload the
user daemon and enable the service:

```bash
systemctl --user daemon-reload
systemctl --user enable --now pybrid-proxy.service
```

`systemctl --user status pybrid-proxy.service` reports the current
state, and the live log is available through the user journal:

```bash
journalctl --user -u pybrid-proxy.service -f
```

By default a user service only runs while the owning user has an
active login session and is stopped when the last session ends. To
have the proxy survive logouts and reboots, enable _lingering_ for
the user once:

```bash
sudo loginctl enable-linger "$USER"
```

With linger enabled, the user manager is started at boot, and any
`--user` service that has been `enable`d (as above) comes up
automatically with the machine.

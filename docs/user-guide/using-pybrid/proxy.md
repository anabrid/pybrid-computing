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

    The entries in a backend file are plain IP addresses, so every
    time DHCP hands one of your devices a new lease the file needs
    updating. To avoid this, pin each device's address on the DHCP
    server (a static reservation keyed on the device's MAC). Once
    done, the backend file effectively becomes a permanent
    description of your setup.

A single backend entry is a string of the form
`HOST[:PORT][/STACK/CARRIER]`. The host part is either an IP address
or a DNS name; the port defaults to `5732` when omitted. The optional
`/STACK/CARRIER` suffix supplies the device's location inside a REDAC
and is discussed in the next section. Inside a backend file, there is
one such entry per line; blank lines and lines beginning with `#` are
ignored.

For quick one-offs, `-b` also accepts the same entries inline:

- A single spec, e.g. `-b 192.168.150.57` or
  `-b 192.168.150.57:5732/0/0`.
- A comma-separated list of specs in one argument, e.g.
  `-b 192.168.150.57/0/0,192.168.150.58/0/1`.

### Choosing between LUCIDAC and REDAC backend lists

The decision between the two list styles is driven entirely by which
hardware sits behind the proxy.

A proxy in front of one or more **LUCIDACs** (each of which is a
single, self-contained device) uses bare host entries without any
location suffix. The proxy treats the listed devices as a flat set of
equivalent carriers with no spatial relationship between them. A
single-device list, taken from
`examples/proxy/list-lucidac-daniel.txt`, is as short as it gets:

```
192.168.150.17
```

Multiple LUCIDACs behind the same proxy (a "LUCIStack") are listed
one per line, still without a suffix
(`examples/proxy/list-lucistack-bernd.txt`):

```
192.168.150.15
192.168.150.57
```

A proxy in front of a **REDAC**, by contrast, must carry location
information for each mREDAC. A REDAC is assembled from one or more
iREDACs, where each iREDAC is itself a physical stack that groups
several mREDACs. `pybrid` needs the `STACK/CARRIER` pair to route
signals between mREDACs correctly: the `STACK` index identifies the
iREDAC, and the `CARRIER` index identifies the mREDAC within that
iREDAC. A single mREDAC is therefore written as
`HOST/STACK/CARRIER` even when no other mREDACs are present
(`examples/proxy/list-mredac-single.txt`):

```
192.168.150.69/0/0
```

A full iREDAC is a contiguous block of entries sharing the same
`STACK` index, with `CARRIER` indices running from `0` upwards, one
per mREDAC in the stack. The MAC addresses in the `#`-comments make
it easy to cross-check the list against the device labels, as in
`examples/proxy/list-iredac0-prod.txt`:

```
# 04-E9-E5-17-E5-67
192.168.110.91/0/0

# 04-E9-E5-18-14-88
192.168.110.98/0/1

# ... five more carriers at 0/2 through 0/6 ...
```

A full REDAC assembly is then several such blocks on top of each
other, one per iREDAC, with `STACK` indices `0`, `1`, `2`, ... and
`CARRIER` indices restarting from `0` inside each iREDAC (see
`examples/proxy/list-redac-0.txt`).

!!! warning "Missing location information on REDAC backends"

    If you pass bare host entries for a REDAC, `pybrid` issues a
    warning along the lines of _"Without REDAC addresses, all
    carriers will be treated equal"_ and will not be able to route
    signals automatically between carriers. The warning is safe to
    ignore for pure LUCIDAC setups but indicates a broken
    configuration for a REDAC.

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

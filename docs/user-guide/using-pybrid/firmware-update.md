# Firmware update (OTA)

LUCIDAC and REDAC devices can be updated over the network from the
`pybrid` CLI, without unplugging the device or attaching it to a host
over USB. The wire protocol carries the firmware image as a regular
message over the same TCP connection used for configuration, so the
device only needs to be reachable from the machine running `pybrid`.

## Prerequisites

- The device must already run firmware version `2.2.0` or newer.
  OTA support landed in `2.2.0`; older devices cannot receive an
  update over the network and have to be flashed once over USB from
  the development host (see the device's operator manual for the USB
  flashing procedure). After that one-off USB update, all future
  updates can run via OTA.
- A quick sanity check: if `pybrid ping HOST` succeeds, the `update`
  command will work as well. Both use the same TCP control channel,
  so reachability and authentication are identical.
- The firmware image (a `.hex` or vendor-supplied bundle) must be
  available as a local file on the machine running `pybrid`.

!!! warning "Do not interrupt an OTA update"

    Power-cycling the device, killing `pybrid`, or losing the network
    link in the middle of an update can leave the device in a state
    that needs a USB recovery flash. Make sure the host is on AC
    power and the network link is stable before starting.

## How to update

The `update` subcommand is available under both the `lucidac` and the
`redac` device groups. The invocation is the same in both cases;
choose the group that matches your hardware.

For a LUCIDAC:

```bash
uv run pybrid lucidac -h 192.168.150.17 update path/to/firmware.hex
```

For a REDAC (one `-h` per mREDAC if you want to update several
carriers in one run; otherwise one `-h` is enough):

```bash
uv run pybrid redac -h 192.168.150.91 update path/to/firmware.hex
```

The command opens a session, transfers the image, asks the device to
apply it, and waits for the device to come back online. Progress is
printed to stdout. On success the command exits with status `0`; on
failure it prints the device's error message and exits non-zero.

## Verifying the update

Once the command returns, run `pybrid ping HOST` again to confirm the
device has rebooted and is responsive. The firmware version is also
included in the entity tree returned by

```bash
uv run pybrid lucidac -h 192.168.150.17 extract --specification
```

so you can cross-check that the version string matches what you just
flashed.

## Updating behind a proxy

Updating devices that sit behind a [proxy](./proxy.md) works
transparently: point `pybrid` at the proxy's address instead of the
device's, and the proxy forwards the update to the selected backend.
Note that the proxy serialises clients, so the OTA update will wait
in the proxy's session queue if another client is currently
configuring or running a circuit.

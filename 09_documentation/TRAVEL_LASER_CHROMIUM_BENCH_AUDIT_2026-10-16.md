# Travel Laser Chromium Bench Audit

## Audit status

Read-only audit performed against the exact SSH alias `laser` on 2026-10-16.
No packages were installed, no persistent permissions changed, and the Travel
Laser service remained active throughout this audit.

Host facts:

- Orange Pi Zero 3, `aarch64`, Armbian 26.11 / Debian 13.7.
- Kernel `6.18.52-current-sunxi64`.
- 969 MiB RAM, 484 MiB swap, approximately 733 MiB available at audit time.
- Root filesystem: 29 GiB total, 27 GiB available.
- Existing validated Python venv: Python 3.13.5 with `spidev`, `gpiod`, and
  `smbus2` available. Its `sys.path` includes Debian `dist-packages`.
- `/dev/spidev1.1`, `/dev/i2c-2`, `/dev/gpiochip1`, and `/dev/uinput` exist.
- Travel Laser UI was active and enabled, with approximately 24.3 MiB current
  service memory at audit time.

Missing renderer components:

- Chromium ARM64 binary.
- Pillow.
- websocket-client.
- python-evdev, which is optional for the compositor-backed `uinput` path and
  is not required by the preferred headless CDP path.
- X11, Wayland, Weston, Cage, and other compositor binaries.

Device permissions:

- SPI, I2C, and GPIO nodes are `root:<hardware group>` mode `0660`.
- `/dev/uinput` is `root:root` mode `0600`.
- The `pi` account is in `input` but not the `spi`, `i2c`, or `gpio` groups.
- The existing `travel-laser` service account is in the hardware groups.
- The reversible runner therefore uses the existing sudo policy for the
  temporary handover rather than changing persistent group membership.

## Candidate installation plan

The read-only Debian simulation with `--no-install-recommends` resolved 50 new
packages:

```sh
sudo apt-get install --no-install-recommends \
  chromium python3-pil python3-websocket python3-evdev
```

Current package metadata reported approximately:

- Download: 122.9 MiB.
- Installed package footprint including dependencies: 453.0 MiB.
- Chromium itself: 300,329 KiB installed, 79.1 MiB download.
- Chromium common data: 85,924 KiB installed, 36.3 MiB download.
- Python packages together: approximately 2.7 MiB installed.

The existing root filesystem has sufficient space, but Chromium runtime memory
must be measured on this 1 GiB board. The renderer should be budgeted against
the observed 733 MiB available memory, with the browser, Python bridge, and
Travel Laser service never running together during the handover.

No graphical desktop environment is required. The selected renderer is
headless Chromium with the Chrome DevTools Protocol, capturing 480x320 frames
and sending dirty RGB565 rectangles to the existing ST7796U driver. The CDP
touch sink receives FT6336U events directly, so no X11/Wayland compositor or
`uinput` permission is needed for the preferred path.

The optional compositor-backed path additionally needs `python3-evdev`, a
running compositor, and a reviewed udev/group rule for `/dev/uinput`. No such
rule should be installed for this bench unless the CDP path proves unsuitable.

## Risks and reversal

`travel-laser-ui.service` currently owns the SPI and I2C devices. Running the
HomeControl bridge concurrently would be unsafe and is forbidden. The runner
records its active/enabled state before a handover, stops it only after
`--approve-hardware-handover`, and restores it afterward.

Preparation and recovery commands:

```sh
./.venv/bin/python 10_scripts/travel_laser_bench.py preflight
./.venv/bin/python 10_scripts/travel_laser_bench.py stage
./.venv/bin/python 10_scripts/travel_laser_bench.py test --role RCM --dry-run
./.venv/bin/python 10_scripts/travel_laser_bench.py restore
```

The dry-run `test` command performs the same read-only preflight and prints the
handover/restore plan without stopping anything. The real `test` command
refuses to stop the service when the renderer dependencies are missing. If a
local session crashes after an approved handover, run the
same `restore` command again from the repository; it reads the remote state
record and only kills recorded HomeControl test PIDs before restoring the
Travel Laser service. It does not issue laser, relay, E-stop, or GPIO output
commands.

The audit found no additional system service requirement. Chromium is launched
and terminated by the temporary display bridge. Package installation, udev
changes, group changes, and the hardware handover all require separate explicit
approval and are intentionally not performed by this change.

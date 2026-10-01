# HomeControl Install Flow

## HCM

Run on the HCM:

```bash
06_config/01_HCM/install.sh
```

The HCM installer clones or pulls `https://github.com/pengels22/HomeControl.git`
into `/opt/HomeControl`, creates the Python virtual environment, installs
dependencies, copies the HCM config to `/etc/homecontrol/01_HCM`, installs
`homecontrol-hcm.service`, enables it, and starts it.

The HCM service also serves the deployment web interface from `01_HCM/www`.
Users are stored in PostgreSQL with PBKDF2 password hashes; plain-text passwords
are never stored. Pairing keys for the 3.5-inch HCM screen, panels, and modules
are stored only as hashes. The clear pairing key is returned only once when it
is generated.

After PostgreSQL is initialized, create the first admin locally on the HCM:

```bash
/opt/HomeControl/.venv/bin/python /opt/HomeControl/10_scripts/create_admin_user.py patrick
```

Useful overrides:

```bash
HC_REPO_URL=https://github.com/pengels22/HomeControl.git
HC_BRANCH=main
HC_INSTALL_ROOT=/opt/HomeControl
HC_SKIP_START=1
```

## Linux Modules

Each Linux module config folder has its own `install.sh`:

- `02_SIM/install.sh`
- `03_LCM/install.sh`
- `04_RCM/install.sh`
- `05_PNL/install.sh`

The installer clones or pulls the repo into `/opt/HomeControl`, creates the
Python virtual environment, copies the device config folder to
`/etc/homecontrol/<device>`, installs the module systemd template, enables the
matching `homecontrol-module@...` service, enables the update service, and
starts both services unless `HC_SKIP_START=1`.

LCM config includes the I2C mux and MCP4725 DAC layout for `10-1` through
`10-8`. Each DAC uses the same address behind a different mux channel. I2C bus
access is disabled by default in config and can be enabled on hardware after the
bus number and mux/DAC addresses are confirmed.

SIM config includes three SocketCAN loops: CAN A on `can0`, CAN B on `can1`,
and CAN C on `can2`. The SIM installer runs `02_SIM/post_install.sh`, which
adds `homecontrol-sim-can.service` so the CAN links are configured at boot.

Each Linux module also serves a local status web UI. The module UI accepts only
an HCM-issued bearer token; if the browser has no token or the token is invalid,
the module prompts for HCM username/password and proxies login to HCM. Module
web pages are status-only and do not provide direct app-to-module control.

Default module web ports:

- SIM: `8092`
- LCM: `8093`
- RCM: `8094`
- PNL: `8095`

## Mac Simulator

Run the local simulator on macOS:

```bash
.venv/bin/python 10_scripts/simulate_homecontrol.py
```

Open `http://127.0.0.1:8088`. The simulator instantiates SIM, LCM, RCM, and
PNL agents in dry mode, injects RMC CAN telemetry using the `06_RMC/RMC.ino`
frame layout, and provides functional HCM/HVAC, relay, dimmer, panel, and RMC
test actions without touching real GPIO, I2C, CAN, PostgreSQL, or systemd.

## IO Mode

Modules use the same code for real hardware and simulation. IO mode is selected
at startup:

- `HCM_DEV_MODE=true` or `HC_DEV_MODE=true` forces simulated IO.
- `HC_IO_MODE=simulated` or `HC_IO_MODE=real` overrides config.
- `io.mode: auto` in module config resolves to real IO when dev mode is not set.

This lets development pages and the Mac simulator exercise the same command
paths while keeping physical buses untouched until hardware deployment.

## HCM Push Helper

From the HCM repo checkout, copy a config folder to a device and run its
installer:

```bash
10_scripts/provision_device_config.sh RCM orangepi@192.168.60.20
10_scripts/provision_device_config.sh LCM orangepi@192.168.60.30
10_scripts/provision_device_config.sh SIM orangepi@192.168.60.40
10_scripts/provision_device_config.sh PNL orangepi@192.168.60.50
```

The helper copies `06_config/common` and the selected device config folder to
the remote device, then runs that folder's `install.sh`. If a Linux module
folder is copied by itself, its `install.sh` can still bootstrap by cloning or
pulling the repo into `/opt/HomeControl` first.

## RMC

RMC is a microcontroller CAN room node, not a Linux service target. The
`06_RMC` folder is reserved for the Arduino `.ino` firmware and its pinned
hardware map.

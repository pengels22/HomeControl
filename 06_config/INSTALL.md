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
The OPI3 loads `can`, `can_raw`, and `gs_usb`; FYSETC Hexa/UCAN candleLight
USB-to-CAN interfaces should then enumerate as SocketCAN `can*` links. The
service applies the configured bitrate and runs `setup_can.py --check` to catch
missing enabled interfaces before the SIM service starts.
SIM state also advertises the supported RMC sensor stack from config: AHT21
temperature/humidity, ENS160 AQI, BH1750 lux, RCWL-0516 presence, and the
MCP2515/TJA1050 CAN interface.
The Hexa board is modeled as a SIM capability manifest covering AIO, DIO, USB,
CAN, and 24V switching. ADC1 monitors the 3.3V bus, ADC2 monitors the 5V bus,
ADC3 monitors loop A 12V, and ADC4 monitors loop B 12V. The simulator exposes
these states on the SIM module page so unused Hexa functions still have a stable
configuration and API surface before full hardware drivers are attached.

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

Open `http://127.0.0.1:8088` on the Mac running the simulator, or the
advertised simulator URL shown in the pairing QR from the iOS app/device network. The simulator instantiates SIM, LCM, RCM, and
PNL agents in dry mode, injects RMC CAN telemetry using the `06_RMC/RMC.ino`
frame layout, and provides functional HCM/HVAC, relay, dimmer, panel, and RMC
test actions without touching real GPIO, I2C, CAN, PostgreSQL, or systemd.
The simulator binds to `0.0.0.0` by default so the iOS app can reach it over
Wi-Fi. Set `HC_SIM_HOST=127.0.0.1` for localhost-only development. The pairing
QR advertises the Mac's current reachable IPv4 address by default; set
`HC_SIM_PUBLIC_URL=http://host:8088` when advertising a specific address.

The HCM screen mockup displays the current secure pairing code inside the
circular pairing UI. The scan target itself is a standards-compliant QR URL
such as `http://<mac-ip>:8088/pair?payload=...`; the query value is still
the opaque `HC2:...` pairing payload that HCM verifies:

```bash
curl http://127.0.0.1:8088/api/pairing-glyph
```

To verify the pairing exchange manually:

```bash
PAYLOAD=$(curl -sS http://127.0.0.1:8088/api/pairing-glyph \
  | .venv/bin/python -c 'import json,sys; print(json.load(sys.stdin)["payload"])')
curl -sS -X POST http://127.0.0.1:8088/api/pairing-glyph/compare \
  -H 'Content-Type: application/json' \
  -d "{\"payload\":\"$PAYLOAD\"}"
```

The response should include `ok: true` and a session token.

## iOS Companion App

The iOS project is in `12_IOS/Home Control`.

The primary pairing path is:

1. HCM displays the QR pairing code inside the circular pairing UI.
2. The app scans the QR using the camera.
3. The app extracts the opaque `HC2` payload from the pairing URL.
4. The app posts that payload to HCM.
5. HCM verifies/decrypts the payload using its local secret.
6. HCM returns an app session token and the app loads the HCM configuration page.

The HCM pairing secret is not stored in the iOS app. The iOS Simulator has no
real camera; use the app's `Load Simulator` action while developing against
the advertised simulator URL. A physical iPhone must point the HCM URL at the
HCM or Mac simulator address reachable from the phone, not `127.0.0.1`.

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
hardware map. `06_RMC/rmc.yaml` records the BOM-backed sensor stack and CAN
hardware expected by the firmware: ENS160+AHT21 combo board, BH1750, RCWL-0516,
MCP2515/TJA1050, and the 4-bit address DIP switch.

RMC firmware updates are orchestrated by HCM and physically delivered by the
assigned SIM over CAN. The update path is always HCM -> SIM -> CAN -> RMC. HCM
builds and sends a complete RMC firmware package to the SIM, the SIM stages and
validates it under `/var/lib/hcm/firmware-staging`, then the SIM runs the
stop-and-wait Classical CAN transfer. The RMC bootloader is protected and owns
application flash programming; normal field updates must never overwrite the
bootloader. HCM/SIM validate SHA-256 package integrity, while the Nano
bootloader is expected to verify the application image with CRC32 before marking
the single application image VALID.

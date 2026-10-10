# HCM Hardware Map

> **Status note (2026-10-10):** The Jetson Xavier NX is now a working **software development HCM** (Docker/Python 3.13 and PostgreSQL, with native Python 3.6 Heartbeat V3). A full host reboot recovered the stack on 2026-10-10. See the [Jetson deployment runbook](../JETSON_HCM_DEPLOYMENT_2026-10-10.md). The hardware map and wiring below are **not validated by that deployment**; physical GPIO safety pathways remain simulated/unconnected.


This file records hardware known from the repository and pasted architecture
brief. It does not finalize unverified wiring, electrical protection, or GPIO
polarity.

## Development Hardware

### Jetson Development HCM

Known from the newer brief:

- Ubuntu 18.04.6 with NVIDIA Tegra 4.9 kernel.
- Python 3.6 compatibility required for `00_Heartbeat/`.
- Hostname `jetson`.
- Ethernet `192.168.1.63`.
- Lab 42 Wi-Fi `192.168.20.27`.
- Ethernet MAC `48:b0:2d:87:db:16`.
- SSH TCP 22.
- Heartbeat TCP 6004.
- Dual network interfaces require source-based policy routing for VLAN 20
  access. Preserve the existing routing solution.

The Jetson is development hardware and must not be assumed to share pinout or
interface layout with the planned Orange Pi 6 HCM.

### Conflict Manager

Known from the newer brief:

- Orange Pi Zero 2W.
- Hostname `conflict`.
- Armbian.
- Current IP `192.168.20.26`.
- SSH account `pi`, passwordless sudo.
- Current identity MAC `3c:53:bb:f7:ad:b2`.
- Heartbeat endpoint TCP 6004.
- Future `eth0` management network `192.168.20.26`.
- Future `eth0.60` heartbeat VLAN address `192.168.60.2/24`.

This processor must boot and supervise independently of the primary HCM
application.

### Planned Main HCM

The planned HCM controller is an Orange Pi 6 with:

- Two 256 GB NVMe devices in Linux software RAID1.
- AX210-class Wi-Fi/Bluetooth card.
- Dedicated wired fire relay input.
- Network architecture:
  - VLAN 20 is the current HCM development/control network.
  - VLAN 40 is the future production HCM control network; subnet not approved.
  - VLAN 60 is heartbeat/supervisory only, with Conflict Manager at
    `192.168.60.2` on `eth0.60`.
  - VLAN 140 is not applicable.

Exact Orange Pi 6 GPIO, SPI, I2C, UART, and CAN assignments are not proven by
hardware validation in the repository.

## HCM Pinout

`06_config/01_HCM/Pinout.md` currently documents:

| Signal | Hardware address | Function | Field voltage |
|---|---|---|---|
| `FIRE_3V3` | Physical Pin 17 | Fire input reference power | 3.3 VDC |
| `FIRE_DI` | Physical Pin 19 / GPIO28 | Fire alarm digital input | 3.3 V logic |
| `FIRE_GND` | Physical Pin 24 | Fire input ground | 0 V |
| `PANEL_3V3` | Physical Pin 1 | Front panel reference | 3.3 VDC |
| `LINK1_LED` | Physical Pin 3 | Link 1 LED | 3.3 V logic |
| `LINK2_LED` | Physical Pin 5 | Link 2 LED | 3.3 V logic |
| `STATUS_LED` | Physical Pin 7 | Status LED | 3.3 V logic |
| `PANEL_GND` | Physical Pin 9 | Front panel ground | 0 V |
| `FAULT_LED` | Physical Pin 11 | Fault LED | 3.3 V logic |
| `ACTION_BUTTON` | Physical Pin 13 | Front panel action button | 3.3 V logic |

This pinout is tested only through parser tests. It is not a validated hardware
driver.

## Fire And AC Monitoring

Repository conflict:

- `09_documentation/PINNED_ARCHITECTURE.md` says fire input is `HIGH = normal`,
  `LOW = fire active`.
- The newer brief says the most recent SPDT contact arrangement is NO -> 3.3 V,
  Common -> GPIO, NC -> Ground, with normal LOW and alarm HIGH if the relay is
  normally de-energized.

Do not implement or change fire input driver behavior until the actual relay,
polarity, input conditioning, debounce, electrical protection, and fail behavior
are confirmed. Three-wire SPDT contacts alone do not prove supervised-circuit
wire integrity.

The newer brief also calls for separate AC-present contacts/poles allocated to
independent processors. No production AC-present input driver was found in the
repo review.

## RCM Hardware

Pinned relay names:

- `A1-A8`
- `B1-B8`
- `C1-C8`
- `D1-D8`

`06_config/04_RCM/Pinout.md` maps:

- Bank A and B to `MCP0 A0-B7`.
- Bank C and D to `MCP1 A0-B7`.
- Selector, LED, action-button, and override inputs to `MCP2`.

BOM and docs identify:

- Waveshare MCP23017 expanders.
- ELEGOO 5 V opto-isolated relay boards.
- Dry-contact field outputs.
- Pluggable terminal connectors.
- Per-channel fail action as a planned/configured concept.

Current code simulates relay state and validates pinout presence. It does not
drive MCP23017 hardware yet.

## LCM Hardware

`06_config/03_LCM/Pinout.md` documents:

- `A1-A8`: lighting relay channels 1-8 on `MCP0 A0-A7`.
- `B1-B4`: lighting relay channels 9-12 on `MCP0 B0-B3`.
- `B5-B8`: high-voltage dimmer override relays.
- `C1-C8`: low-voltage dimmers `10-1` through `10-8`, using mux channels 0-7
  and MCP4725 DACs.
- `D1-D4`: Shelly high-voltage dimmer channels `HV-1` through `HV-4`.
- `D5-D8`: reserved.
- `E*` and `F*`: selector, status, link, fault, action, and override inputs.

LCM BOM/config includes:

- TCA/PCA9548A I2C multiplexer at `0x70`.
- MCP4725-based 0-10 V DAC modules at `0x60` behind the mux.
- Eight 0-10 V output labels `10-1` through `10-8`.
- Four high-voltage Shelly dimmer channels.

I2C is disabled by default in config and must be enabled only after bus and
address validation on hardware.

## SIM Hardware

`06_config/02_SIM/Pinout.md` and `sim.yaml` document:

- A1-A8 analog inputs via ADS1115 devices at `0x48` and `0x49`.
- Loop monitor ADS1115 at `0x4A`.
- CAN loops:
  - CAN A on FYSETC Hexa CAN0 / `can0`.
  - CAN B on UCAN1 / `can1`.
  - CAN C on UCAN2 / `can2`.
- Hexa DIO, USB, CAN, and 12 V switching manifest.
- 12 V loop monitor statuses for loops A-C plus spare loop D.

The SIM installer loads `can`, `can_raw`, and `gs_usb`, and creates
`homecontrol-sim-can.service` to configure SocketCAN links.

## RMC Hardware

RMC hardware is documented in `06_config/06_RMC/`:

- HiLetgo Nano 3.0 Type-C / ATmega328P-class controller.
- MCP2515 CAN controller and TJA1050 transceiver.
- ENS160 + AHT21 environmental sensor.
- BH1750 light sensor.
- RCWL-0516 presence sensor.
- 4-bit DIP address switch, address range 0-15.
- 12 V field input with local 5 V buck converter.

Pinned Nano pins:

- D2 CAN interrupt.
- D3 RCWL-0516 presence.
- D4-D7 DIP address bits.
- D10 CAN chip select.
- D11-D13 SPI.
- A4/A5 I2C.

CAN frame bases:

- Telemetry `0x100`.
- Heartbeat `0x200`.
- Fault `0x300`.
- Fault clear `0x400`.
- SIM-to-RMC update `0x600`.
- RMC-to-SIM update `0x680`.

## PNL Hardware

Docs describe PoE wall panels using an Orange Pi Zero-class controller, 7-inch
touchscreen, PoE splitter, Linux kiosk, Chromium, and a panel agent. Current
code stores room and dashboard URL only. Final panel hardware validation and UI
are planned.

## HVAC Hardware

Pinned HVAC hardware/behavior:

- HCM acts as thermostat.
- R->G, R->Y, and R->W calls are logical relay outputs.
- Spring-open / power-close damper actuators.
- Failed room sensor causes that room damper to default open.
- Master bedroom, office, and guest room are non-actuated/permanently open in
  seed data to preserve airflow paths.

Relay channels for actual HVAC calls and dampers must be bound through
PostgreSQL logical devices, not hardcoded hardware addresses.

## Validation Gaps

The following require confirmation before production hardware use:

- Orange Pi 6 physical pin numbering and GPIO naming.
- Fire relay polarity, debounce, isolation, protection, and fail states.
- AC-present relay allocation and polarity.
- Relay board active-high/active-low behavior.
- MCP23017 addressing and bus topology.
- LCM DAC output scaling and electrical interface to LED drivers.
- Shelly dimmer integration details.
- CAN bitrate consistency: `sim.yaml` uses 125000 bps while RMC config/firmware
  references 250000 bps.
- Fuse sizing and terminal schedules.
- Maintenance-lock electrical behavior for outputs that may also be required by
  life-safety actions.

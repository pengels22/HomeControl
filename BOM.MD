# HomeControl Bill of Materials

Status: First-pass BOM based on the HCM architecture pinned to date.

This file separates:
- parts and hardware families that have already been selected or explicitly pinned;
- parts whose exact model, rating, quantity, or implementation still needs to be decided.

Quantities marked **per module**, **as required**, or **per circuit** are intentional because the final house-wide device count has not yet been frozen.

---

## Pinned Parts

### 1. HCM — House Control Module

| Item | Pinned selection / requirement | Qty | Notes |
|---|---|---:|---|
| Central controller | **Orange Pi 6** | 1 | HCM central controller. Uses both onboard 2.5 GbE interfaces. |
| HCM NIC 1 | Onboard 2.5 GbE | 1 | Switch Port 1. VLAN membership `U1,T20`. |
| HCM NIC 2 | Onboard 2.5 GbE | 1 | Switch Port 2. Untagged VLAN 60. HCM address `192.168.60.1/24`. |
| HCM control switch | **16-port managed switch** | 1 | Port 1 = OPI6 `U1,T20`; Port 2 = OPI6 `U60`; Ports 3-16 = HCM modules `U60`. Exact switch model remains to be selected. |
| Fire alarm interface relay | **Kidde/SM120X-compatible smoke alarm interconnect relay module** | 1 | Off-the-shelf fire relay interface. Dedicated HCM fire input. |
| Fire input | Direct OPI6 DI | 1 | Normal = HIGH, fire = LOW. Separated from normal MCP-based I/O. |

### 2. Digital I/O Expansion

| Item | Pinned selection / requirement | Qty | Notes |
|---|---|---:|---|
| GPIO expander | **Waveshare MCP23017 16-channel I2C expansion module** | As required | 5 V MCP-based digital I/O expansion. |
| I2C multiplexer | **AITRIP PCA/TCA9548A 8-channel I2C multiplexer breakout** | Per LCM analog section / as required | Used to isolate/select identical-address I2C devices, including the 0-10 V DAC channels. |

### 3. Relay Hardware / RCM

| Item | Pinned selection / requirement | Qty | Notes |
|---|---|---:|---|
| Relay boards | **ELEGOO-style 5 V optocoupled relay boards** | As required | Use 2-, 4-, or 8-channel versions according to output count. MCP-controlled. |
| Relay logic supply | **5 VDC** | Per module | Matches MCP/relay control electronics. |
| Relay contact style | Dry contact, COM/NO/NC | 1 per channel | Field side electrically isolated from logic side. |
| RCM output count | 32 outputs | Per full RCM | Four banks of eight outputs. |
| Relay bank naming | `A1-A8`, `B1-B8`, `C1-C8`, `D1-D8` | — | Physical/logical channel numbering standard. |
| Relay field connectors | **10-position pluggable PCB terminal connectors, Phoenix-style** | 4 per 32-output RCM | One connector per 8-channel bank. |
| Field feed grouping | One common feed per 4 relay channels | 2 feeds per 8-channel bank | Connector layout supports one feed for channels 1-4 and one for 5-8. |
| Relay fail behavior | Software-configurable fail action per output | — | Existing HCM I/O design requirement. |

### 4. LCM — Lighting Control Module

| Item | Pinned selection / requirement | Qty | Notes |
|---|---|---:|---|
| 0-10 V DAC module | **Aptinex DA1C010BI / MCP4725-based 0-10 V module** | 8 per LCM requiring analog dimming | One DAC per dimming channel. |
| I2C multiplexer | **PCA/TCA9548A 8-channel mux** | 1 per 8 analog channels | One mux channel per DAC. |
| Analog dimming outputs | 8 total | Per LCM | Labels `10-1` through `10-8`. |
| Analog field wiring | **24 AWG / 2-conductor, 600 V-rated wire** | 8 dedicated pairs per LCM | Hardwired, one signal/analog-ground pair per dimmer. |
| Analog routing | **C3 conduit/raceway** | 8 pairs | 0-10 V pairs are hardwired through C3 to the LED drivers. |
| 0-10 V LED drivers | **0-10 V dimmable LED driver family** (linked Amazon part) | Per lighting circuit | Driver wattage/output selected per lighting load. |
| High-voltage dimming | Shelly dimming devices | As required | Used where high-voltage dimming is appropriate instead of 0-10 V. |
| LCM relay connectors | 10-position pluggable PCB terminal connectors | As required | Relay termination only; **0-10 V dimming is hardwired and does not use Phoenix connectors**. |

### 5. SIM / RMC

| Item | Pinned selection / requirement | Qty | Notes |
|---|---|---:|---|
| RMC controller | Arduino Nano-class controller | 1 per RMC | Previously pinned RMC controller architecture. |
| CAN controller/transceiver | MCP2515 + TJA1050 | 1 per RMC | RMC-to-SIM communications. |
| Ambient light sensor | BH1750 | 1 per RMC | Room light level. |
| Occupancy/motion sensor | RCWL-0516 | 1 per RMC | Room monitoring cluster occupancy sensing. |
| Air-quality sensor | ENS160 | 1 per RMC | Air-quality sensing. |
| Temperature/humidity sensor | AHT21 | 1 per RMC | Room temperature/humidity source used by HCM logic. |
| RMC local power | 12 V input + local 5 V buck | 1 per RMC | 12 V field standard with local electronics conversion. |
| CAN connectors | Dual parallel CAN connectors | 2 per RMC | Carry `12V / GND / CAN-H / CAN-L`. |
| RMC addressing | 4-bit DIP switch | 1 per RMC | Addresses `0-15`, read at boot. |
| CAN capacity | 16 addresses per CAN loop | — | Three CAN loops were pinned in the RMC/SIM architecture. |

### 6. PNL — Wall Panel

| Item | Pinned selection / requirement | Qty | Notes |
|---|---|---:|---|
| Panel computer | **Orange Pi Zero** | 1 per panel | Linux kiosk / Chromium / panel agent. |
| Display | **7-inch touchscreen** | 1 per panel | Permanent room wall panel. |
| Panel power | **5 V Gigabit PoE splitter** (linked Amazon part) | 1 per panel | PoE network/power feed converted to panel power. |
| Ethernet panel feedthrough | **iGreely panel-mount RJ45 extension** | As required | Panel/enclosure Ethernet connection. |
| Panel network | VLAN 60 | 1 connection per panel | PNL addresses begin at `192.168.60.50`. |

### 7. HVAC Control

| Item | Pinned selection / requirement | Qty | Notes |
|---|---|---:|---|
| HVAC control relays | MCP-controlled dry-contact relay channels | 3 primary calls | HCM replaces the thermostat. |
| HVAC calls | `R->G`, `R->Y`, `R->W` | — | Fan, cooling, heating. HVAC `C` is not required for HCM dry-contact call generation. |
| HVAC damper actuators | **M847D1004-compatible 24 VAC spring-return damper actuator** | Per actuated zone | Power-close / spring-open behavior supports fail-open zoning. |
| Damper relays | RCM/general relay outputs | Per actuated zone | HCM owns zoning logic. |
| Non-actuated zones | Master bedroom, office, guest room | 3 zones currently pinned | Remain open to prevent system deadheading. |
| HVAC control band | ±1 °F | Software setting | Global mode and setpoint. |
| Cooling minimum run | 2 minutes | Software setting | `Y` minimum active time except higher-priority shutdown. |
| Heating minimum run | 1 minute | Software setting | `W` minimum active time except higher-priority shutdown. |
| Cooling restart lockout | 5 minutes | Software setting | `Y` anti-short-cycle protection. |
| Heating restart lockout | 5 minutes | Software setting | `W` restart protection. |
| Fan post-run | 60 seconds | Software setting | Fan remains on after heat/cool call ends. |
| Start sequence | Damper -> 500 ms -> Fan -> 500 ms -> Heat/Cool | Software timing | Dampers continue moving while airflow starts; always-open zones prevent deadheading. |

### 8. Field Wiring / Termination

| Item | Pinned selection / requirement | Qty | Notes |
|---|---|---:|---|
| Standard field control voltage | **12 VDC** | System-wide | Normal HCM field voltage standard. |
| Local electronics rail | **5 VDC** | As required | MCP expanders, relay boards, controllers, panel electronics as applicable. |
| 0-10 V cable | **24 AWG / 2C, 600 V-rated** | 8 pairs per LCM analog section | Dedicated hardwired pair per analog output. |
| Relay terminal connectors | **10-position pluggable PCB terminal blocks** | Per relay bank | Phoenix-style connector family selected. |
| RJ45 | Panel-mount RJ45 extensions / Ethernet cabling | As required | Ethernet connections. |
| IEC | IEC power connectors | As required | AC/removable power connections where used. |
| Field splicing | Wago lever connectors / wire nuts | As required | Cabinet and field branch connections. |
| Conduit/raceway | C-numbered conduits/raceways | As designed | Wiring documentation uses conduit schedules rather than manufactured harness schedules. |
| Terminal numbering | `1-X` | Per terminal strip/connector | Simple sequential terminal numbering. |

### 9. Circuit Protection

| Item | Pinned selection / requirement | Qty | Notes |
|---|---|---:|---|
| Fuse holders | **6x30 mm panel fuse holders with indicator** (linked uxcell part) | Per protected branch | Form factor pinned. |
| Fuses | **6x30 mm, 250 V glass fuses** | Per protected branch | Current rating is selected per circuit. The linked 8 A fuse is one available value, not a universal system fuse. |

### 10. Rack / Enclosures

| Item | Pinned selection / requirement | Qty | Notes |
|---|---|---:|---|
| 2U enclosure | **2U rackmount chassis** (Amazon ASIN `B0D41ZJH3D`) | As required | Used according to the existing module layout. |
| 1U enclosure | **RackChoice shallow 1U Mini-ITX rackmount chassis** (Amazon ASIN `B0B3MG34D1`) | As required | Used according to the existing rack/module layout. |

### 11. Network Address Allocation

This is not a purchased part, but it is pinned and affects switch/router configuration.

| Device class | Address allocation |
|---|---|
| HCM | `192.168.60.1` |
| RCM | `192.168.60.20-29` |
| LCM | `192.168.60.30-39` |
| SIM | `192.168.60.40-49` |
| PNL | `192.168.60.50+` |

VLAN 60 mask: `255.255.255.0`.

Modules retain their assigned address after commissioning.

---

# still_needed

The following items still require an exact part selection, quantity, rating, or final design decision.

## HCM / Networking

- **Exact 16-port managed switch model.**
  - Must support the pinned port/VLAN layout:
    - Port 1: `U1,T20`
    - Port 2: `U60`
    - Ports 3-16: `U60`
- **Orange Pi 6 exact RAM/storage variant.**
- **HCM system storage device** if not included/onboard.
- **UPS model and runtime target** for the HCM/control network, if the final build will be UPS-backed.
- Final network patch cable lengths/counts.

## Power Distribution

- Exact **12 VDC power supply** model(s) and wattage.
- Exact **5 VDC supply / buck converter** model(s) and current rating for each module family.
- Exact **24 VAC transformer** capacity for HVAC damper actuators if the existing HVAC transformer will not be used.
- Final branch-by-branch fuse ratings.
- Final AC distribution hardware, including any breakers, distribution blocks, and disconnects not already part of the rack equipment.
- Exact grounding/bonding hardware and terminal blocks where required.

## RCM / LCM / SIM Electronics

- Final quantity of:
  - MCP23017 boards per module;
  - 2-, 4-, and 8-channel relay boards per module;
  - PCA/TCA9548A mux boards;
  - Aptinex 0-10 V DAC boards.
- Exact PCB/perfboard/carrier-board mounting method for breakout modules.
- Standoffs, DIN adapters, or custom mounting plates.
- Final internal 5 V and 12 V distribution connectors.
- Any local transient suppression or additional protection required beyond the selected relay-board circuitry.

## Lighting

- Exact LED driver **wattage/current/voltage variant per lighting circuit**.
- Final count of 0-10 V circuits versus Shelly-controlled high-voltage dimming circuits.
- Exact Shelly dimmer model(s) for each high-voltage dimming application.
- Final LED fixture/strip/load selections where not already defined elsewhere.
- Final 0-10 V pair lengths for C3 conduit fill documentation.

## HVAC

- Exact quantity and duct size for the actuated dampers.
- Exact physical damper bodies/blades to pair with the M847D1004-compatible actuators.
- Exact 24 VAC load calculation for all damper actuators.
- Final HVAC relay-bank/channel assignments.
- Final temperature-sensor/RMC placement by room.
- Confirm which additional rooms, if any, will be permanently non-actuated beyond:
  - master bedroom;
  - office;
  - guest room.

## Fire / Life Safety

- Exact SM120X-compatible relay manufacturer/listing to purchase for the final installation.
- Final GPIO input conditioning/protection details between the fire relay dry contact and the OPI6 input.
- Final fire-relay cable type and route.
- Final service/test disconnect or maintenance-test hardware, if any beyond the software Maintenance Lock.
- Final labeling required at the fire relay/HCM termination.

## PNL

- Exact Orange Pi Zero model/revision.
- Exact 7-inch touchscreen model.
- Exact wall-box/enclosure and trim/bezel.
- Final PoE splitter connector/output variant matching the selected panel hardware.
- Exact mounting brackets/hardware.

## RMC / SIM

- Exact Arduino Nano-compatible board manufacturer/version.
- Exact MCP2515/TJA1050 breakout board.
- Exact 12 V-to-5 V buck converter.
- Exact connector family for the dual CAN/power ports.
- Exact DIP switch part.
- Final RMC enclosure/mounting method.
- Final RMC quantities and room placement.

## Connectors / Wiring / Raceway

- Exact manufacturer/series/part number for the 10-position pluggable terminal connector once mechanical pitch and PCB footprint are frozen.
- Exact Wago connector families/counts by location.
- IEC inlet/outlet exact parts and ratings.
- Final conductor gauges for every non-0-10 V circuit.
- Final conduit/raceway sizes and fill calculations.
- Cable labels / heat-shrink label stock.
- Ferrules, ring terminals, spade terminals, and crimp tooling as required.

## Rack / Mechanical

- Final count of 1U and 2U chassis.
- Exact rack rail/shelf requirements.
- Internal DIN rail lengths.
- Wire duct/raceway sizes.
- Cooling fan quantities and any fan guards/filters.
- Rack power distribution unit if required.
- Faceplate labels and engraving/printing method.

## Software-Adjacent Hardware

- Development/debug USB cables for each controller type.
- Spare relay boards, MCP expanders, muxes, DAC modules, RMC sensors, and PoE splitters.
- Optional local service keyboard/display hardware if desired for rack maintenance.

---

## BOM Revision Notes

This BOM should be updated whenever:
1. an exact manufacturer/model is selected for an item in `still_needed`;
2. a module hardware revision changes;
3. a circuit count changes;
4. a new HCM module type is introduced;
5. a previously generic field device becomes a standardized part.

Recommended future BOM columns once purchasing begins:

`Part ID | Manufacturer | Manufacturer P/N | Description | Module | Qty/Module | Total Qty | Supplier | Supplier SKU/ASIN | Revision | Notes`

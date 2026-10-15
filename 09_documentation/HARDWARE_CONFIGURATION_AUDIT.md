# Hardware Configuration Audit

**Revision:** 2026-10-15
**Authority:** `HomeControl_Full_System_Pinout_v1.md`
**Implementation status:** authoritative manifests added; physical commissioning remains outstanding

## Scope and safety boundary

This audit covers application code, module configuration, shared I/O helpers,
deployment manifests, system services, diagnostics, and tests. No live device,
firmware, GPIO overlay, network configuration, service, or physical output was
changed. All new profiles set `physical_output_enabled: false` and retain the
existing simulation and safety arbitration paths.

The master pinout is the Source of Truth for the active design. `UNVERIFIED`
means the repository must not infer an electrical connection, Linux GPIO line,
polarity, connector position, or commissioned hardware capability.

## Findings and corrections

| Area | Finding | Severity | Correction/status |
|---|---|---:|---|
| LCM analog outputs | `lcm.yaml` described the retired PCA9548A/MCP4725 design and only eight 0-10V channels. | High | Active YAML and manifest now use PCA9685 `0x40`, PWM0-PWM9, ten channels, PWM10-PWM15 reserved. |
| LCM relay inventory | Legacy docs exposed twelve relay-like channels and mixed Shelly control contacts with user outputs. | High | Manifest defines A1-A8 only; four Shelly control relays are explicitly non-user-facing. |
| LCM HV outputs | Physical identity and four Shelly channels were not represented as one authoritative mapping. | High | Manifest maps HV-1..HV-4 to two Shelly Pro Dimmer 2PM devices by permanent identity slot. RPC remains disabled. |
| RCM relay hardware | Legacy `Pinout.md` named MCP0/MCP1 relay mappings. | High | Manifest and active diagnostics use XL9535 cards at `0x20`/`0x21`, preserving A1-D8 logical names. |
| RCM faceplate | Override and bank controls were mixed into the legacy relay pin table. | Medium | Manifest separates MCP1 override inputs and MCP2 bank selectors/LEDs. Bank truth table remains UNVERIFIED. |
| Orange Pi headers | Individual module documents did not provide a complete 26-position inventory. | High | SIM, LCM, and RCM manifests enumerate every position, including power, ground, reserved, and unused positions. |
| Jetson header | HCM `Pinout.md` conflicted with the approved Jetson 40-pin design. | High | HCM manifest and documentation now use the 40-pin Type C SOT; FIRE is physical pin 38 and AC-present is pin 40. |
| HCM safety helpers | Simulated safety relay code contained stale numeric GPIO claims. | High | Numeric claims removed; FIRE references physical pin 38 and unresolved Linux mappings remain UNVERIFIED. Simulation backend is preserved. |
| SIM Hexa wiring | Connector-level Hexa pin assignments are not available in verified material. | High | CAN, ADS1115, and logical Hexa functions remain represented; connector pins are explicitly UNVERIFIED. |
| Shared validation | No common schema checked header completeness, I2C/SPI conflicts, or commissioning gates. | High | `07_servises/common/hardware_profiles.py` validates all active profiles and rejects unsafe real-output enablement. |
| Front panel | No commissioned SPI/touch hardware driver exists. | Medium | Hardware-independent profile/diagnostic data is available; physical display/touch adapters remain deferred. |
| Shelly | No verified RPC identity/discovery contract exists. | High | Shelly channels are descriptive and disabled; no direct command path was added. |
| CAN/USB/Ethernet | Logical services and interfaces exist, but physical connector and electrical validation are incomplete. | Medium | Existing SocketCAN and module configuration are preserved; no live network changes were made. |

## Authoritative files

- `06_config/01_HCM/hardware_pins.yaml`
- `06_config/02_SIM/hardware_pins.yaml`
- `06_config/03_LCM/hardware_pins.yaml`
- `06_config/04_RCM/hardware_pins.yaml`
- `07_servises/common/hardware_profiles.py`

The module `manifest.yaml` files now include the corresponding hardware
manifest. Module entrypoints validate the profile before starting normal module
operation. The RCM command response derives its hardware address from the
validated XL9535 manifest rather than the retired Markdown mapping.

## Physical inventory status

### Designed and represented

- Orange Pi Zero 3 Type A/B 26-pin header positions.
- Jetson Type C 40-pin header positions.
- RCM 32 logical relay outputs and XL9535 intended indices.
- LCM 8 relay, 10 analog, and 4 HV logical outputs.
- LCM PCA9685 output allocation and reserved outputs.
- Type A MCP1/MCP2 functional groups.
- SIM ADS1115 addresses and CAN interface names.

### Simulated only

- RCM/LCM relay and dimmer state.
- PCA9685/PWM-to-0-10V output behavior.
- Shelly dimmer behavior.
- Front-panel display, touch, LEDs, and override switches.
- HCM safety relay backend.

### UNVERIFIED / requires commissioning

- Exact Linux GPIO line numbers and pinmux overlays.
- LCD board schematic, backlight enable, touch interrupt/reset, and current budget.
- MCP/XL9535/PCA9685 board strap addresses and level-shifter wiring.
- Relay polarity, input loading, boot inactive state, and contact feedback.
- RCM Phoenix terminal positions, shared-common ratings, and field harnesses.
- LCM converter calibration, missing-PWM behavior, Shelly switch input wiring,
  Shelly identities, VLAN 512 switch configuration, and mains barriers.
- SIM Hexa connector pins, CAN transceivers, analog terminals, and 12V wiring.
- HCM AC-present electrical polarity and all physical safety conditioning.

## Preserved functionality

- HCM remains the authority for logical bindings and command routing.
- LAB1 simulation and physical-output inhibition are unchanged.
- Maintenance lockout, life-safety arbitration, and heartbeat supervision are unchanged.
- Existing RCM 32-channel logical names and LCM 22-channel logical inventory are preserved.
- Existing CAN firmware update and simulator behavior remain available.
- No direct browser-to-hardware path was introduced.

## Remaining implementation limits

The profile loader validates configuration and exposes structured capability data;
it does not claim physical commissioning. A future hardware-driver phase must
add device-specific adapters behind the same profile and safety gates, with
bench evidence before changing any `physical_output_enabled` value.

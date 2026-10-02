# Home Controller / UniFi Build — Updated BOM

**Current running total (before tax/shipping): $7,871.09**

- Amazon / HCM / automation hardware: **$2,794.09**
- UniFi network / Protect / Access: **$5,077.00**

> Notes:
> - The standalone AHT20 sensors have been removed; RMCs use the ENS160+AHT21 combo boards.
> - HCM storage is 2 × 256GB NVMe in RAID1.
> - UNVR storage is 2 × 8TB WD Red Pro in RAID1.
> - Orange Pi boards, wall-panel displays, rack/patch infrastructure, fiber/SFP modules, bulk Cat6, UPS hardware, and the gate operator itself are not yet included unless specifically listed below.

---

## 1. HCM — House Control Module

| Item | Qty | Unit | Ext. | Purpose | Link |
|---|---:|---:|---:|---|---|
| Patriot P320 256GB PCIe Gen3x4 M.2 2280 NVMe | 2 | $56.99 | $113.98 | HCM RAID1 storage | [Amazon](https://www.amazon.com/Patriot-P320-256GB-Internal-SSD/dp/B0D4S1F5R6/) |
| OKN AX210NGW Wi-Fi 6E + Bluetooth M.2 2230 | 1 | $24.64 | $24.64 | HCM E-Key wireless/Bluetooth | [Amazon](https://www.amazon.com/OKN-AX210NGW-Bluetooth-Wireless-Ultra-Low/dp/B08MJLPZPL/) |
| SM120X-compatible smoke relay module | 1 | $15.99 | $15.99 | Wired fire alarm dry-contact input | [Amazon](https://www.amazon.com/SM120X-Interconnect-Accessories-Module-408-Sm120X/dp/B0F6JVQWHJ/) |
| GPERHUAN 2U rack chassis | 1 of 3 | $65.30 | $65.30 | HCM chassis | [Amazon](https://www.amazon.com/dp/B0D41ZJH3D/) |
| Apevia ITX-AP300W 300W PSU | 1 | $35.99 | $35.99 | HCM/SIM PSU allocation | [Amazon search](https://www.amazon.com/s?k=Apevia+ITX-AP300W+300W) |
| Orange Pi 6 | 1 | TBD | TBD | Main HCM controller | [Orange Pi](http://www.orangepi.org/html/hardWare/computerAndMicrocontrollers/details/Orange-Pi-6.html) |

**Pinned HCM storage:** 2 × 256GB NVMe → Linux software RAID1 → ~256GB usable.

---

## 2. RCM — Relay Control Module

| Item | Qty | Unit | Ext. | Purpose | Link |
|---|---:|---:|---:|---|---|
| GPERHUAN 2U rack chassis | 1 of 3 | $65.30 | $65.30 | RCM chassis | [Amazon](https://www.amazon.com/dp/B0D41ZJH3D/) |
| Waveshare MCP23017 I/O expander | 3 | $12.99 | $38.97 | Relay + selector/LED/override I/O | [Amazon](https://www.amazon.com/Waveshare-MCP23017-Expansion-Interface-Expands/dp/B07P2H1NZG/) |
| ELEGOO 8-channel 5V relay board, 2-pack | 2 packs | $17.38 | $34.76 | 4 physical relay boards / 32 outputs | [Amazon](https://www.amazon.com/ELEGOO-Channel-Optocoupler-Compatible-Raspberry/dp/B09ZQRLD95/) |
| Ruiwaer 12pcs 5×20 PCB fuse holders | 3 packs | $7.99 | $23.97 | 32 fused relay outputs + spares | [Amazon search](https://www.amazon.com/s?k=Ruiwaer+12pcs+5X20+PCB+fuse+holder) |
| 10-position 5.08mm Phoenix-style connector, 2-set pack | 2 packs allocated | $7.59 | $15.18 | Four 8-output relay-bank connectors | [Amazon](https://www.amazon.com/Terminal-Connector-Pluggable-Connector-300V-AWG24-12/dp/B0GSZM4MGX/) |
| Gigabit PoE → USB-C 5V 3.5A splitter | 1 of 9 | $13.99 | $13.99 | RCM power | [Amazon](https://www.amazon.com/2-Pack-Gigabit-Splitter-Active-Adapter/dp/B0GQZ8DTMD/) |

**Pinned RCM output banks:** A1–A8, B1–B8, C1–C8, D1–D8.

---

## 3. LCM — Lighting Control Module

| Item | Qty | Unit | Ext. | Purpose | Link |
|---|---:|---:|---:|---|---|
| GPERHUAN 2U rack chassis | 1 of 3 | $65.30 | $65.30 | LCM chassis | [Amazon](https://www.amazon.com/dp/B0D41ZJH3D/) |
| Waveshare MCP23017 I/O expander | 2 | $12.99 | $25.98 | Relay + override/control I/O | [Amazon](https://www.amazon.com/Waveshare-MCP23017-Expansion-Interface-Expands/dp/B07P2H1NZG/) |
| ELEGOO 8-channel 5V relay board, 2-pack | 1 pack | $17.38 | $17.38 | 2 physical relay boards | [Amazon](https://www.amazon.com/ELEGOO-Channel-Optocoupler-Compatible-Raspberry/dp/B09ZQRLD95/) |
| Aptinex VoltPulse DA1C010BI 0–10V DAC | 8 | $39.00 | $312.00 | Eight native 0–10V lighting outputs | [Amazon](https://www.amazon.com/Aptinex-Module-DA1C010BI-Digital-MCP4725/dp/B07K64GLTF/) |
| TCA9548A I2C mux, 6-pack | 1 | $9.99 | $9.99 | Isolates/address-selects eight DAC channels | [Amazon](https://www.amazon.com/AITRIP-PCSTCA9548A-Multiplexer-Breakout-Expansion/dp/B08JGSMRF9/) |
| 12V 60W 0–10V dimmable LED driver | 8 | $38.94 | $311.52 | LED driver channels | [Amazon](https://www.amazon.com/Dimmable-Transformer-Compatible-Constant-Waterproof/dp/B0FM3HQC2Z/) |
| Gigabit PoE → USB-C 5V 3.5A splitter | 1 of 9 | $13.99 | $13.99 | LCM control power | [Amazon](https://www.amazon.com/2-Pack-Gigabit-Splitter-Active-Adapter/dp/B0GQZ8DTMD/) |
| Energeaster 100ft 16/2 low-voltage wire | 1 | $9.99 | $9.99 | LED/low-voltage distribution | [Amazon search](https://www.amazon.com/s?k=Energeaster+100FT+16AWG+16%2F2) |

**Pinned 0–10V wiring:** eight dedicated 24AWG/2-conductor pairs, labels 10-1 through 10-8, hardwired through C3.

---

## 4. SIM — Sensor Interface Module

| Item | Qty | Unit | Ext. | Purpose | Link |
|---|---:|---:|---:|---|---|
| Rackchoice 1U compact chassis | 1 | $76.00 | $76.00 | SIM chassis | [Amazon](https://www.amazon.com/gp/aw/d/B0B3MG34D1/) |
| ViaGasaFamido 6-channel CAN hub ("Hexa Board") | 1 | $42.12 | $42.12 | CAN distribution | [Amazon search](https://www.amazon.com/s?k=ViaGasaFamido+6+Channel+CANBUS+Expansion+USB2517) |
| FYSETC UCAN board | 2 | $15.19 | $30.38 | USB-to-CAN interfaces | [Amazon search](https://www.amazon.com/s?k=FYSETC+UCAN+Board+V1.0+STM32F072) |
| 10-position Phoenix-style connector, 2-set pack | 1 pack allocated | $7.59 | $7.59 | SIM field connection allocation | [Amazon](https://www.amazon.com/Terminal-Connector-Pluggable-Connector-300V-AWG24-12/dp/B0GSZM4MGX/) |
| iGreely RJ45 panel-mount extender, 2-pack | 2 packs | $8.99 | $17.98 | Panel-mount Ethernet | [Amazon](https://www.amazon.com/Ethernet-Extender-iGreely-Network-Extension/dp/B082SJ88MS/) |

---

## 5. RMC — Room Monitoring Clusters (12 total)

| Item | Qty purchased | Unit | Ext. | Coverage | Link |
|---|---:|---:|---:|---|---|
| HiLetgo Nano 3.0 Type-C, 3-pack | 4 packs | $16.49 | $65.96 | 12 RMCs | [Amazon search](https://www.amazon.com/s?k=HiLetgo+3pcs+Nano+3.0+ATmega328P+Type-C) |
| ENS160 + AHT21 combo, 3-pack | 4 packs | $19.99 | $79.96 | 12 RMCs | [Amazon search](https://www.amazon.com/s?k=ENS160+AHT21+3pcs+ACEIRMC) |
| RCWL-0516 motion sensor, 12-pack | 1 | $9.99 | $9.99 | 12 RMCs | [Amazon search](https://www.amazon.com/s?k=DWEII+12PCS+RCWL-0516) |
| BH1750 light sensor, 3-pack | 4 packs | $11.99 | $47.96 | 12 RMCs | [Amazon search](https://www.amazon.com/s?k=ACEIRMC+3pcs+BH1750) |
| 5V 3A buck converter, 6-pack | 2 packs | $8.99 | $17.98 | 12 RMCs | [Amazon search](https://www.amazon.com/s?k=AKEYSRC+6+Pack+5V+Buck+Converter+3A) |
| MCP2515 + TJA1050 CAN module, 5-pack | 3 packs | $8.99 | $26.97 | 12 used + 3 spare | [Amazon search](https://www.amazon.com/s?k=EC+Buying+5Pcs+MCP2515+TJA1050) |
| 4-position DIP switch, 20-pack | 1 | $6.49 | $6.49 | RMC CAN addresses | [Amazon search](https://www.amazon.com/s?k=20pcs+4+Position+DIP+Switch+2.54mm) |
| 4-pin 5.08mm Phoenix-style connector, 5-set pack | 5 packs | $8.27 | $41.35 | 24 dual CAN/power connectors + spare | [Amazon search](https://www.amazon.com/s?k=5+Set+4+Pin+5.08mm+Phoenix+Connector+XUGERIP) |

**RMC sensor stack:** ENS160+AHT21 + RCWL-0516 + BH1750. Standalone AHT20 is removed.

---

## 6. PNL — Wall Panels

| Item | Qty | Unit | Ext. | Purpose | Link |
|---|---:|---:|---:|---|---|
| Gigabit PoE → USB-C 5V 3.5A splitter | 7 of 9 | $13.99 | $97.93 | 7 wall panels | [Amazon](https://www.amazon.com/2-Pack-Gigabit-Splitter-Active-Adapter/dp/B0GQZ8DTMD/) |
| Orange Pi Zero-class panel controller | 7 | TBD | TBD | Panel compute | TBD |
| 7-inch touchscreen | 7 | TBD | TBD | Panel HMI | TBD |

---

## 7. HVAC / Dampers

| Item | Qty | Unit | Ext. | Purpose | Link |
|---|---:|---:|---:|---|---|
| M847D1004-compatible 24VAC spring-return damper actuator | 7 | $35.89 | $251.23 | Seven actuated HVAC zones | [Amazon](https://www.amazon.com/M847D1004-Actuator-Compatible-Honeywell-M847D1012/dp/B0DHR8RFLH/) |

Pinned safe state: spring-open / power-close. Master bedroom, office, and guest room remain non-actuated to prevent deadheading.

---

## 8. UniFi Network / Protect / Access

| Item | Qty | Unit | Ext. | Location / use |
|---|---:|---:|---:|---|
| UniFi Standard 24 PoE | 1 | $379 | $379 | Shop |
| UniFi Switch 48 PoE | 1 | $589 | $589 | MDF |
| UniFi Pro XG 8 PoE | 1 | $499 | $499 | She Shed |
| UniFi Switch Aggregation | 1 | $269 | $269 | Fiber backbone / STP |
| UniFi Dream Machine Pro | 1 | $379 | $379 | Gateway/controller |
| UniFi U7 Lite | 5 | $99 | $495 | 3 house, 1 shop, 1 She Shed |
| UniFi G5 Bullet 3-pack | 2 | $359 | $718 | 6 cameras |
| UniFi AI Pro | 1 | $499 | $499 | Gate / LPR camera |
| UniFi UNVR | 1 | $299 | $299 | Protect recorder |
| UniFi Redundant Power | 1 | $399 | $399 | Power redundancy |
| UniFi SmartPower Cable | 4 | $29 | $116 | RPS connections |
| UniFi PoE Smart Chime | 3 | $79 | $237 | Doorbell/chime locations |
| UniFi Door Hub — standard | 1 | $199 | $199 | Gate dry-contact + position input |

**UniFi subtotal: $5,077.00**

Store: [Ubiquiti UniFi](https://store.ui.com/us/en)

---

## 9. Protect Storage

| Item | Qty | Unit | Ext. | Purpose | Link |
|---|---:|---:|---:|---|---|
| WD Red Pro 8TB 7200RPM CMR HDD | 2 | $379.99 | $759.98 | UNVR RAID1, ~8TB usable | [Amazon](https://www.amazon.com/Western-Digital-Plus-Internal-Drive/dp/B0D1V2K4LJ/) |

Target: 7 cameras / approximately 7 days continuous recording with redundancy.

---

## 10. Current Amazon / Automation Cost Summary

The latest Amazon/home-automation list, including the two Red Pro drives, totals:

**$2,794.09**

This includes the RMC hardware, module electronics, chassis, dampers, LED drivers, HCM SSDs/Wi-Fi card, PoE splitters, relay/DAC/I/O hardware, CAN hardware, and the two 8TB UNVR drives.

---

## 11. Not Yet Priced / Still Needed

These are part of the architecture but are **not included in the $7,871.09 running total unless added later**:

- Orange Pi 6 HCM board
- RCM / LCM / SIM compute boards where not already owned
- 7 panel controller boards
- 7 × 7-inch panel displays
- HCM/RMC/PNL enclosure internals, standoffs, custom PCBs, small hardware
- 24AWG 2-conductor 600V-rated cable for LCM 0–10V channels
- Individual 5×20mm fuses sized per RCM output circuit
- DIN/raceway / internal panel wire / Wago terminals as required
- Bulk Cat6 and outdoor/direct-burial Cat6
- Fiber runs
- SFP/SFP+ optics or DACs
- Patch panels and patch cords
- Rack(s) / cable management
- UPS / surge protection
- Gate operator, keypad, exit loop, and buried loop detector hardware
- Hidden gate-position reed/proximity switch + neodymium magnet
- Outdoor gate enclosure / small PoE distribution hardware if required
- Any doorbell cameras/readers not yet specified

---

# Grand Total So Far

**Amazon / HCM / automation:** $2,794.09  
**UniFi:** $5,077.00  

## **Current defined hardware total: $7,871.09 before tax/shipping**

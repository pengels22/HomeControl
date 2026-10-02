# Ubiquiti BOM — Home Controller Project

_Last updated: 2026-10-02_

This BOM reflects the currently pinned UniFi network / Protect / Access plan. Prices are current U.S. store base prices used in the running project total and do **not** include tax, shipping, UI Care, optional accessories, or current surcharge pricing shown by Ubiquiti.

## Core Network

| Item | Model | Location / Role | Qty | Unit Price | Extended | Link |
|---|---|---|---:|---:|---:|---|
| Standard 24 PoE | USW-24-POE | Shop switch | 1 | $379.00 | $379.00 | https://store.ui.com/us/en/products/usw-24-poe |
| Standard 48 PoE | USW-48-POE | MDF main copper switch | 1 | $589.00 | $589.00 | https://store.ui.com/us/en/products/usw-48-poe |
| Pro XG 8 PoE | USW-Pro-XG-8-PoE | She Shed switch | 1 | $499.00 | $499.00 | https://store.ui.com/us/en/category/all-switching/products/usw-pro-xg-8-poe |
| Aggregation | USW-Aggregation | 10G fiber backbone / aggregation | 1 | $269.00 | $269.00 | https://store.ui.com/us/en/products/usw-aggregation |
| Dream Machine Pro | UDM-Pro | Main UniFi gateway / controller | 1 | $379.00 | $379.00 | https://store.ui.com/us/en/products/udm-pro |

**Core network subtotal: $2,115.00**

## Wi-Fi

| Item | Model | Deployment | Qty | Unit Price | Extended | Link |
|---|---|---|---:|---:|---:|---|
| U7 Lite | U7-Lite | 3 house, 1 shop, 1 She Shed | 5 | $99.00 | $495.00 | https://store.ui.com/us/en/category/all-wifi/products/u7-lite |

**Wi-Fi subtotal: $495.00**

## Protect / Cameras / NVR

| Item | Model | Role | Qty | Unit Price | Extended | Link |
|---|---|---|---:|---:|---:|---|
| G5 Bullet 3-Pack | UVC-G5-Bullet-3 | General exterior cameras; 6 cameras total | 2 packs | $359.00 | $718.00 | https://store.ui.com/us/en/category/physical-security-bullet/products/uvc-g5-bullet?variant=uvc-g5-bullet-3 |
| AI Pro | UVC-AI-Pro | Gate / vehicle / plate-recognition camera | 1 | $499.00 | $499.00 | https://store.ui.com/us/en/products/uvc-ai-pro |
| Network Video Recorder | UNVR | Protect recorder; 4-drive bay | 1 | $299.00 | $299.00 | https://store.ui.com/us/en/category/physical-security-nvr/products/unvr |

**Protect subtotal: $1,516.00**

> Storage plan is separate from this Ubiquiti-only BOM: 2 × 8 TB WD Red Pro drives in RAID1 for about 8 TB usable.

## Access / Gate

| Item | Model | Role | Qty | Unit Price | Extended | Link |
|---|---|---|---:|---:|---:|---|
| Door Hub | UA-Hub-Door | Gate dry-contact control + gate closed-position input | 1 | $199.00 | $199.00 | https://store.ui.com/us/en/products/ua-hub-door |
| PoE Smart Chime | UACC-Chime-PoE | Access / doorbell notification chimes | 3 | $79.00 | $237.00 | https://store.ui.com/us/en/collections/pro-store-doorbells-chimes/products/uacc-chime-poe |

**Access subtotal: $436.00**

### Current gate architecture
- Existing gate operator retains its own keypad, exit loop, motor-limit and safety functions.
- Door Hub provides an additional dry-contact open request to the gate operator.
- AI Pro provides the UniFi vehicle / LPR camera input.
- Gate closed-position status is planned from a hidden normally-open reed/proximity switch under the gate operator housing, actuated by a neodymium magnet on the gate arm.

## Redundant Power

| Item | Model | Role | Qty | Unit Price | Extended | Link |
|---|---|---|---:|---:|---:|---|
| Redundant Power | USP-RPS | UniFi rack equipment redundant DC power | 1 | $399.00 | $399.00 | https://store.ui.com/us/en/products/usp-rps |
| SmartPower Cable | USP-Cable | RPS interconnect cables | 4 | $29.00 | $116.00 | https://store.ui.com/us/en/category/power-tech-other/products/unifi-smartpower-cable |

**Redundant power subtotal: $515.00**

# Ubiquiti Total

| Section | Total |
|---|---:|
| Core network | $2,115.00 |
| Wi-Fi | $495.00 |
| Protect | $1,516.00 |
| Access | $436.00 |
| Redundant power | $515.00 |
| **Grand total** | **$5,077.00** |

## Not yet included / still to be selected

The current $5,077 total does not include:

- SFP / SFP+ optical modules
- Fiber patch cables and building-to-building fiber runs
- DAC cables inside the MDF/rack where useful
- Outdoor Ethernet surge protection at exposed camera / gate locations
- Patch panels, keystones and rack patch cables
- Rack / cabinet hardware
- UPS hardware
- Gate operator itself, keypad, exit-loop hardware or gate safety devices
- Protect HDDs (currently planned separately as 2 × 8 TB WD Red Pro)
- Optional UI Care plans
- Taxes, shipping or Ubiquiti surcharge pricing


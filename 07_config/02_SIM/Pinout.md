| Channel | Hardware Address | Function | Field Voltage |
|---|---|---|---|
| A1 | ADS 0x48 CH0 | Analog Input 1 | Analog |
| A2 | ADS 0x48 CH1 | Analog Input 2 | Analog |
| A3 | ADS 0x48 CH2 | Analog Input 3 | Analog |
| A4 | ADS 0x48 CH3 | Analog Input 4 | Analog |
| A5 | ADS 0x49 CH0 | Analog Input 5 | Analog |
| A6 | ADS 0x49 CH1 | Analog Input 6 | Analog |
| A7 | ADS 0x49 CH2 | Analog Input 7 | Analog |
| A8 | ADS 0x49 CH3 | Analog Input 8 | Analog |
| B1 | HEXA CAN0 | CAN Loop A | 12VDC + CAN |
| B2 | UCAN1 CAN0 | CAN Loop B | 12VDC + CAN |
| B3 | UCAN2 CAN0 | CAN Loop C | 12VDC + CAN |
| B4 | HEXA DIO | Digital IO bank | Logic IO |
| B5 | HEXA USB | USB host/downstream links | USB |
| B6 | HEXA 12V SW | Loop A/B/C power switches | 12VDC |
| B7 | Internal | SIM health / internal monitor | - |
| B8 | Internal | Reserved Hexa expansion | - |

| ADS1115 | Channel | Function |
|---|---|---|
| 0x48 | CH0-CH3 | A1-A4 analog inputs |
| 0x49 | CH0-CH3 | A5-A8 analog inputs |
| 0x4A | CH0 | Loop A 12V monitor |
| 0x4A | CH1 | Loop B 12V monitor |
| 0x4A | CH2 | Loop C 12V monitor |
| 0x4A | CH3 | Loop D spare monitor |

| Phoenix Pin | Signal |
|---|---|
| 1 | AGND |
| 2 | A1 |
| 3 | A2 |
| 4 | A3 |
| 5 | A4 |
| 6 | A5 |
| 7 | A6 |
| 8 | A7 |
| 9 | A8 |
| 10 | AGND |

| Loop | CAN Interface | Power Source | Connector Signals |
|---|---|---|---|
| CAN A | FYSETC Hexa CAN0 | Hexa Port 1 | +12V / GND / CAN-H / CAN-L |
| CAN B | UCAN1 | Hexa Port 2 | +12V / GND / CAN-H / CAN-L |
| CAN C | UCAN2 | Hexa Port 3 | +12V / GND / CAN-H / CAN-L |

Hexa board support manifest:

- AIO is represented by `hexa_board.interfaces.aio` in `sim.yaml`.
- DIO is represented by `hexa_board.interfaces.dio` and can be simulated from the SIM page.
- USB links are represented by `hexa_board.interfaces.usb`.
- CAN links are represented by the existing SocketCAN `can0`, `can1`, and `can2` setup.
- 12V switching is represented by `hexa_board.interfaces.switching_12v` and controls loop A/B/C power, including restart cycling.
- Bus monitors report 3.3V and 5V status.
- Loop monitors use ADS1115 address `0x4A` for loops A-C plus a spare loop D channel.

OPI3 / Linux CAN bring-up:

- The SIM installer loads `can`, `can_raw`, and `gs_usb`.
- FYSETC Hexa / UCAN candleLight USB-to-CAN adapters are expected to enumerate as SocketCAN links.
- `homecontrol-sim-can.service` applies the configured bitrate to `can0`, `can1`, and `can2`.
- `setup_can.py --check` verifies enabled `can*` links exist before the SIM module service starts.

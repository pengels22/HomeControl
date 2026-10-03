| Channel | Hardware Address | Function | Field Voltage |
|---|---|---|---|
| A1 | Hexa ADC1 | 3.3V bus monitor | 3.3VDC |
| A2 | Hexa ADC2 | 5V bus monitor | 5VDC |
| A3 | Hexa ADC3 | Loop A 12V monitor | 12VDC |
| A4 | Hexa ADC4 | Loop B 12V monitor | 12VDC |
| A5 | ADC1 CH0 | Analog Input 5 | Analog |
| A6 | ADC1 CH1 | Analog Input 6 | Analog |
| A7 | ADC1 CH2 | Analog Input 7 | Analog |
| A8 | ADC1 CH3 | Analog Input 8 | Analog |
| B1 | HEXA CAN0 | CAN Loop A | 12VDC + CAN |
| B2 | UCAN1 CAN0 | CAN Loop B | 12VDC + CAN |
| B3 | UCAN2 CAN0 | CAN Loop C | 12VDC + CAN |
| B4 | HEXA DIO | Digital IO bank | Logic IO |
| B5 | HEXA USB | USB host/downstream links | USB |
| B6 | HEXA 24V SW | 24V switched outputs | 24VDC |
| B7 | Internal | SIM health / internal monitor | - |
| B8 | Internal | Reserved Hexa expansion | - |

| Hexa ADC | SIM Input | Function |
|---|---|---|
| ADC1 | A1 | 3.3V bus monitor |
| ADC2 | A2 | 5V bus monitor |
| ADC3 | A3 | Loop A 12V monitor |
| ADC4 | A4 | Loop B 12V monitor |
| ADC5 | A5 | Spare analog input |
| ADC6 | A6 | Spare analog input |
| ADC7 | A7 | Spare analog input |
| ADC8 | A8 | Spare analog input |

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
- 24V switching is represented by `hexa_board.interfaces.switching_24v` and can be simulated from the SIM page.
- ADC1 monitors the 3.3V bus, ADC2 monitors the 5V bus, ADC3 monitors loop A 12V, and ADC4 monitors loop B 12V.

OPI3 / Linux CAN bring-up:

- The SIM installer loads `can`, `can_raw`, and `gs_usb`.
- FYSETC Hexa / UCAN candleLight USB-to-CAN adapters are expected to enumerate as SocketCAN links.
- `homecontrol-sim-can.service` applies the configured bitrate to `can0`, `can1`, and `can2`.
- `setup_can.py --check` verifies enabled `can*` links exist before the SIM module service starts.

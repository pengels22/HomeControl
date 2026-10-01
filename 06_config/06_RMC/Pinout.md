| Pin | Hardware Address | Function | Field Voltage |
|---|---|---|---|
| D0 | Nano D0 | USB / Serial RX Reserved | 5V Logic |
| D1 | Nano D1 | USB / Serial TX Reserved | 5V Logic |
| D2 | Nano D2 | MCP2515 CAN Interrupt | 5V Logic |
| D3 | Nano D3 | RCWL-0516 Presence Output | 5V Logic |
| D4 | Nano D4 | Address DIP Bit 0 | 5V Logic |
| D5 | Nano D5 | Address DIP Bit 1 | 5V Logic |
| D6 | Nano D6 | Address DIP Bit 2 | 5V Logic |
| D7 | Nano D7 | Address DIP Bit 3 | 5V Logic |
| D8 | Nano D8 | Spare Digital I/O | 5V Logic |
| D9 | Nano D9 | Spare Digital I/O | 5V Logic |
| D10 | Nano D10 | MCP2515 Chip Select | 5V Logic |
| D11 | Nano D11 | MCP2515 SPI MOSI | 5V Logic |
| D12 | Nano D12 | MCP2515 SPI MISO | 5V Logic |
| D13 | Nano D13 | MCP2515 SPI SCK | 5V Logic |
| A0 | Nano A0 | Spare Analog Input | 0–5V |
| A1 | Nano A1 | Spare Analog Input | 0–5V |
| A2 | Nano A2 | Spare Analog Input | 0–5V |
| A3 | Nano A3 | Spare Analog Input | 0–5V |
| A4 | Nano A4 / SDA | I²C SDA — Sensors | 5V Logic |
| A5 | Nano A5 / SCL | I²C SCL — Sensors | 5V Logic |
| A6 | Nano A6 | Spare Analog Input Only | 0–5V |
| A7 | Nano A7 | Spare Analog Input Only | 0–5V |

| Device | Interface | Function |
|---|---|---|
| BH1750 | A4 SDA / A5 SCL | Ambient Light |
| ENS160 | A4 SDA / A5 SCL | Air Quality / VOC |
| AHT21 | A4 SDA / A5 SCL | Temperature / Humidity |

| Signal | Hardware |
|---|---|
| CAN Interrupt | Nano D2 |
| CAN CS | Nano D10 |
| SPI MOSI | Nano D11 |
| SPI MISO | Nano D12 |
| SPI SCK | Nano D13 |
| CAN Controller | MCP2515 |
| CAN Transceiver | TJA1050 |

| DIP Bit | Nano Pin | Weight |
|---|---|---:|
| ADDR0 | D4 | 1 |
| ADDR1 | D5 | 2 |
| ADDR2 | D6 | 4 |
| ADDR3 | D7 | 8 |

That gives each RMC an address of 0–15, sampled at startup. Each SIM CAN loop therefore supports the previously established 16 RMC addresses per loop. 
RMC CAN / Power connectors
Both CAN connectors are internally paralleled:
Connector Pin	Signal	Field Voltage
1	+12V	12VDC
2	GND	0V
3	CAN-H	CAN
4	CAN-L	CAN


Power internally is:
12V field input → local 5V buck → Nano + sensors + CAN electronics.
The RMC has a termination jumper available, but normal topology uses termination only at the end of the CAN run rather than at every RMC.
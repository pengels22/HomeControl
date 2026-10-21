# HomeControl — Full System Hardware Pinout
**Revision:** Working design baseline, 2026-10-15  
**Modules:** HCM (Type C), RCM (Type A), LCM (Type A), SIM (Type B)  
**Status:** Orange Pi touchscreen mapping follows the validated Travel Laser reference; physical header numbers, NOT Linux GPIO line numbers. Remaining panel wiring and startup behavior still require bench verification.

## 0. Rules and conventions
- All enclosures are **2U**. Front panel A: LCD/touch, POWER/LINK/STATUS/FAULT LEDs, eight SPDT center-off override switches, two bank-select switches. B: LCD/touch and four LEDs (SIM). C: electrically Jetson-specific version of B (HCM).
- RCM/LCM/SIM computer: **Orange Pi Zero 3, 1 GB, 26-pin header**. HCM computer: **Jetson, 40-pin header**.
- 3.3V processor GPIO must never be driven from a 5V output. On Type A, the 5V MCP23017/PCA9685/relay-expander bus is behind a bidirectional I²C level shifter. The touchscreen is on its 3.3V side; single logical I²C bus.
- Physical positions are viewed **looking down onto the male processor header**, pin 1 at the upper-left of each two-column diagram. Loom female-plug views are mirrored if viewed from mating side; verify key orientation before crimping.
- Active-low relay control: GPIO/MCP logic high should mean *relay OFF* only if verified on the actual input circuitry; passive inactive-state hardware is required during boot. MCP/GPIO source/sink capabilities must be tested; use an interface driver if needed.
- The RCM relay contact section and LCM relay/Shelly mains contact sections require physical LV/HV barriers, appropriately rated connectors, insulation, and PE-bonded chassis. **PE/chassis is not AC neutral and is not automatically DC negative.**
- No pin described as 'proposed' is a validated Linux kernel pinmux or safe startup state.

## 1. Orange Pi Zero 3 — master 26-pin header
Source: Orange Pi Zero 3 H618 user manual, 26-pin interface section. SPI peripheral on this header is **SPI1**; I²C is **TWI3/I²C3**.

```
         ODD (left)                               EVEN (right)
  3.3V / faceplate power           [ 1] [ 2]     5V (do not feed display from here)
  PH5 / I2C3 SDA (touch+LV shift)   [ 3] [ 4]     5V
  PH4 / I2C3 SCL (touch+LV shift)   [ 5] [ 6]     GND
  PC9 / TOUCH INT UNUSED            [ 7] [ 8]     PH2 / LCM 4CH relay IN1 (GPIO/UART5 TX)
  GND                               [ 9] [10]     PH3 / LCM 4CH relay IN2 (GPIO/UART5 RX)
  PC6 / LCD D/C                    [11] [12]     PC11 / LCM 4CH relay IN3
  PC5 / TOUCH RESET                [13] [14]     GND
  PC8 / SIM LINK LED               [15] [16]     PC15 / LCM 4CH relay IN4
  3.3V (secondary supply)          [17] [18]     PC14 / LCD RESET (unmanaged)
  PH7 / SPI1 MOSI                  [19] [20]     GND
  PH8 / SPI1 MISO (reserved)       [21] [22]     PC7 / SIM FAULT LED
  PH6 / SPI1 CLK                   [23] [24]     PH9 / SPI1 CS1 (LCD)
  GND                               [25] [26]     PC10 / UNUSED
```

| Physical | SoC signal | Common assignment | Type A RCM | Type A LCM | Type B SIM |
|---:|---|---|---|---|---|
| 1 | 3.3V | LCD/touch supply candidate and POWER LED on B | display logic | display logic | display + POWER LED |
| 2 | 5V | control rail access only | optional supply | optional supply | unused for faceplate |
| 3 | PH5 / TWI3 SDA | touchscreen + level shifter LV SDA | same | same | touch SDA |
| 4 | 5V | control rail access only | optional | optional | unused |
| 5 | PH4 / TWI3 SCL | touchscreen + level shifter LV SCL | same | same | touch SCL |
| 6 | GND | panel signal return | GND | GND | GND |
| 7 | PC9 | touch interrupt unused | unused | unused | unused |
| 8 | PH2 / UART5_TX alt | free | free | Shelly relay IN1 | free |
| 9 | GND | return | GND | GND | GND |
| 10 | PH3 / UART5_RX alt | free | free | Shelly relay IN2 | free |
| 11 | PC6 | LCD D/C | LCD D/C | LCD D/C | LCD D/C |
| 12 | PC11 | GPIO | available | Shelly relay IN3 | available |
| 13 | PC5 | touch reset | touch reset | touch reset | touch reset |
| 14 | GND | return | GND | GND | GND |
| 15 | PC8 | GPIO | available | available | LINK LED |
| 16 | PC15 | GPIO | available | Shelly relay IN4 | available |
| 17 | 3.3V | optional auxiliary 3.3V feed | optional | optional | optional |
| 18 | PC14 | LCD reset electrical line, unmanaged by driver | unmanaged | unmanaged | unmanaged |
| 19 | PH7 / SPI1 MOSI | LCD MOSI | LCD | LCD | LCD |
| 20 | GND | SPI return | GND | GND | GND |
| 21 | PH8 / SPI1 MISO | SPI readback reserved | reserve | reserve | reserve |
| 22 | PC7 | GPIO | available | available | FAULT LED |
| 23 | PH6 / SPI1 CLK | LCD clock | LCD | LCD | LCD |
| 24 | PH9 / SPI1 CS1 | LCD CS1 | LCD | LCD | LCD |
| 25 | GND | return | GND | GND | GND |
| 26 | PC10 | unused | unused | unused | unused |

**Notes:** UART5 must be disabled/re-pinned before PH2 and PH3 are used as LCM relay GPIOs. The exact LCD board connectors, backlight enable and touchscreen interrupt/reset requirements have not been mapped from a board schematic. 3.3V header capacity must be checked against display/backlight load. The 5V I²C rail on Type A is not wired directly to the Orange Pi's SDA/SCL.

## 2. Jetson HCM — Type C, 40-pin header
Derived from user-provided Jetson expansion header image; GPIO assignments preserved from HCM design discussions. The Jetson's faceplate is the electrical oddball. FIRE and AC are **separate from the faceplate loom**.

```
  3.3V                                [ 1] [ 2]   5V
  I2C1 SDA (not selected for touch)    [ 3] [ 4]   5V
  I2C1 SCL                            [ 5] [ 6]   GND
  GPIO09 / spare                      [ 7] [ 8]   UART1 TX
  GND                                 [ 9] [10]   UART1 RX
  UART1 RTS / spare                   [11] [12]   I2S0 SCLK
  SPI1 SCK / spare                    [13] [14]   GND
  GPIO12 / spare                      [15] [16]   SPI1 CS1 / spare
  3.3V / LCD + POWER                  [17] [18]   LCD RESET GPIO (SPI1 CS0 alt)
  SPI0 MOSI                           [19] [20]   GND
  SPI0 MISO / reserved                [21] [22]   LCD D/C GPIO (SPI1 MISO alt)
  SPI0 SCK                            [23] [24]   SPI0 CS0
  GND                                 [25] [26]   SPI0 CS1 reserved
  I2C0 SDA / TOUCH                    [27] [28]   I2C0 SCL / TOUCH
  GPIO01 / spare                      [29] [30]   GND
  GPIO11 / spare                      [31] [32]   GPIO07 / spare
  GPIO13 / FAULT LED                  [33] [34]   GND / LED return
  I2S0 FS / LINK LED                  [35] [36]   UART1 CTS / STATUS LED
  SPI1 MOSI / reserved                [37] [38]   FIRE input (I2S0 DIN alt)
  GND                                 [39] [40]   AC present input (I2S0 DOUT alt)
```

| HCM signal | Physical Jetson pin | Notes |
|---|---:|---|
| LCD/TP 3.3V | 17 | current/budget verify |
| POWER LED 3.3V | 17 (or dedicated protected 3.3V takeoff) | LED has built-in limiting resistor; verify 3.3V drive |
| LCD GND | 20/25 | return |
| SPI0 MOSI | 19 | LCD data |
| SPI0 MISO | 21 | reserved unless display uses readback |
| SPI0 SCK | 23 | LCD clock |
| SPI0 CS0 | 24 | LCD chip select |
| LCD D/C | 22 | GPIO mode, alt SPI1 MISO |
| LCD RESET | 18 | GPIO mode, alt SPI1 CS0 |
| Touch SDA | 27 | Jetson I²C0 |
| Touch SCL | 28 | Jetson I²C0 |
| FAULT LED | 33 | GPIO13 |
| LINK LED | 35 | I2S0 FS configured GPIO |
| STATUS LED | 36 | UART1 CTS configured GPIO |
| LED ground | 34 | GND |
| FIRE | 38 | special independent safety input; not routed into LCD harness |
| AC present | 40 | special monitor input; not routed into LCD harness |
| safety ground | 39 | GND |

**Fire relay electrical mapping (latest agreed HCM convention):** independent SM120X SPDT NO -> 3.3V, C -> Jetson GPIO 38, NC -> GND; normal LOW, alarm activated HIGH assuming normal deenergized relay. This **supersedes polarity shown in older 2026 architecture outline**. The Orange Pi independent fire monitor, if fitted, follows its separately approved processor-specific GPIO schedule (do not take Jetson physical pin 38 literally on 26-pin Orange Pi). AC-present monitor has separate DPDT pole per controller, and its input polarity/wiring must be checked against the last approved electrical schematic before termination. Dedicated lockout and 250ms debounce apply per prior agreement.

## 3. Faceplate harness connector J-FP1 — provisional 2x12, common FACEPLATE-side pinout
This describes **front-panel connector pins**, not direct processor header pins. Type A has additional local MCP/relay interconnects and switch wiring; a 24-wire loom by itself is **not** the complete Type A harness if expanders are mounted on the faceplate. Do not let pin names imply two independent I²C buses.

| J-FP1 | Signal | A RCM/LCM source | B SIM source | C HCM source |
|---:|---|---|---|---|
| 1 | LCD_3V3 | OPi 1 via rated rail | OPi 1 | Jetson 17 |
| 2 | TP_3V3 | OPi 1 | OPi 1 | Jetson 17 |
| 3 | GND | OPi 6 | OPi 6 | Jetson 20 |
| 4 | LCD_MOSI | OPi 19 | OPi 19 | Jetson 19 |
| 5 | LCD_MISO/RESERVE | OPi 21 | OPi 21 | Jetson 21 |
| 6 | LCD_CLK | OPi 23 | OPi 23 | Jetson 23 |
| 7 | LCD_CS | OPi 24 (SPI1 CS1) | OPi 24 (SPI1 CS1) | Jetson 24 |
| 8 | LCD_DC | OPi 11 | OPi 11 | Jetson 22 |
| 9 | LCD_RST | OPi 18, unmanaged by driver | OPi 18, unmanaged by driver | Jetson 18 |
| 10 | TP_SDA_3V3 | OPi 3 | OPi 3 | Jetson 27 |
| 11 | TP_SCL_3V3 | OPi 5 | OPi 5 | Jetson 28 |
| 12 | TP_INT | unused in validated driver | unused in validated driver | TBD if fitted |
| 13 | TP_RST | OPi 13 | OPi 13 | TBD if fitted |
| 14 | LCD_BL / EN | TBD board requirement | TBD | TBD |
| 15 | POWER_LED_FEED | MCP2 GPA4 on Type A | 3.3V | 3.3V |
| 16 | LINK_LED | MCP2 GPA5 | OPi 15 | Jetson 35 |
| 17 | STATUS_LED | MCP2 GPA6 | OPi 16 | Jetson 36 |
| 18 | FAULT_LED | MCP2 GPA7 | OPi 22 | Jetson 33 |
| 19 | LED_GND | common GND | common GND | Jetson 34 |
| 20 | GND | OPi 20/25 | OPi 20/25 | Jetson 25 |
| 21 | MCP_LOGIC_5V (A only) | regulated 5V | NC | NC |
| 22 | MCP_SDA_5V (A only) | level shifter HV SDA | NC | NC |
| 23 | MCP_SCL_5V (A only) | level shifter HV SCL | NC | NC |
| 24 | RESERVE | NC | NC | NC |

**IMPORTANT:** Type A LED drive at 5V from MCP2 must match the particular LED assembly and board; Type B/C are 3.3V. The connector signal `POWER_LED_FEED` is deliberately not permanently tied to 3.3V for Type A. Screen compatibility claims (3.3V/5V power and logic) are based on user-confirmed selected hardware; use 3.3V for display and touchscreen per current arrangement. MCP1/MCP2 physical placement and extra cable for Type A switch outputs and relay GPB lines must be specified on assembly drawing. Avoid drawing the entire HV relay current through this small signal connector.

## 4. Type A front-panel I/O — shared RCM/LCM MCP map
All MCP23017 logic supplies: regulated 5V via level-shifted 5V I²C bus. Proposed address straps **MCP1 0x26, MCP2 0x27** (verify board jumpers). Input GPIO pull-ups enabled; contacts close to GND.

| Chip | Port pin | Signal / termination |
|---|---|---|
| MCP1 0x26 | GPA0–GPA7 | Override #1–#8 ON throw (active low) |
| MCP1 0x26 | GPB0–GPB7 | Override #1–#8 OFF throw (active low) |
| MCP1 | switch common ×8 | Ground; one 3-terminal SPDT center-off switch per channel |
| MCP2 0x27 | GPA0–GPA3 | 2 physical bank-select switches; each has 2 throws, commons to GND; 4-bit logical bank encoding retained from RCM design |
| MCP2 0x27 | GPA4 | POWER LED on Type A |
| MCP2 0x27 | GPA5 | LINK LED on Type A |
| MCP2 0x27 | GPA6 | STATUS LED on Type A |
| MCP2 0x27 | GPA7 | FAULT LED on Type A |
| MCP2 0x27 | GPB0–GPB7 | RCM: currently reserved; LCM: 8-ch active-low relay inputs IN1–IN8 |

Override truth table: ON = GPAx LOW, GPBx HIGH; AUTO = both HIGH; OFF = GPAx HIGH, GPBx LOW; both LOW = impossible state/wiring fault. Selector switch detailed bank encoding to be implemented consistently in both Type A panels; logical RCM groups A/B/C/D are four banks.

## 5. RCM (2U, Type A) full I/O
### RCM 5V and logic
- Main AC/DC PSU: **MEAN WELL LRS-100-5**, 5V at 18A (90W). Chassis bonded to protective earth; logic 5V fed via suitable distribution, coils not powered through thin I²C board traces.
- OPi Zero 3 1GB 26pin per §1; one I²C3 bus (3.3V) through bidirectional 3.3↔5V level shifter to MCP1/MCP2 and both relay cards; touch on 3.3V side.
- Relay card 1: **XL9535-K16V5**, intended I²C `0x20`, 16 relays = A1–A8, B1–B8.
- Relay card 2: **XL9535-K16V5**, intended I²C `0x21`, 16 relays = C1–C8, D1–D8.
- Card channel-index mapping must be checked against actual relay numbering at bench; software mapping based on intended card indexes 0–15 for card 1 and 0–15 for card 2.

### RCM 32 switched-output terminal schedule
**Each bank: one shared common and four normally open outputs;** field connector intended Phoenix-style 10A pluggable contacts. Eight banks total. **Single common is limited to its own terminal/conductor/protection rating: DO NOT assume 4×10A is allowed through 10A common.**

| Shared bank common | Output terminals | Relay logical names | Board indexes |
|---|---|---|---|
| C1 | A1, A2, A3, A4 | A1–A4 | card1 0–3 |
| C2 | A5, A6, A7, A8 | A5–A8 | card1 4–7 |
| C3 | B1, B2, B3, B4 | B1–B4 | card1 8–11 |
| C4 | B5, B6, B7, B8 | B5–B8 | card1 12–15 |
| C5 | C1-out, C2-out, C3-out, C4-out | C1–C4 | card2 0–3 |
| C6 | C5-out, C6-out, C7-out, C8-out | C5–C8 | card2 4–7 |
| C7 | D1, D2, D3, D4 | D1–D4 | card2 8–11 |
| C8 | D5, D6, D7, D8 | D5–D8 | card2 12–15 |

*Note nomenclature collision*: `C1` can mean shared Common 1 or logical relay channel C1. Terminal engraving should use `COM1…COM8`, and relay channels `A1…D8` to remove ambiguity. Eight × five-position bank connectors = **40 contact positions** if all commons and NO outputs are accessible. Final field-contact current/voltage/use and isolation must be rated per actual load circuit.

## 6. LCM (2U, Type A) full I/O
### Electrical supplies
- Main **24V/5A 120W** regulated PSU feeds 10 PWM-to-0–10V converters by short protected 24V daisy-chain distribution; independent 24V-to-5V **10A/50W** buck powers Orange Pi, 5V I²C logic/relays, and TP-Link managed switch on star branches.
- Two Shelly Pro Dimmer 2PM devices independently powered from mains; the existing **LCM power-whip scheme** is unchanged. LV/HV separated by enclosure divider; relay field contact terminals entirely on HV side.

### I²C devices and analog outputs
| Device | I²C address | Mapping |
|---|---|---|
| MCP1 | 0x26 | eight override SPDT switches |
| MCP2 | 0x27 | four bank-select contact inputs; four LEDs; 8 × relay inputs on GPB |
| Dorhea PCA9685 | 0x40 | PWM0–PWM9 to converters LV-1…LV-10; PWM10–15 spare |
| Touch controller | TBD I²C address | 3.3V side of one I²C3 bus |

PCA9685 VCC 5V, output driver push-pull nominal 5V PWM, ~1kHz proposed; the selected **AOICRIE B0B1J56GR5** PWM-to-0–10V modules (ten total) powered from 24V. Converter input voltage/frequency, calibrations and actual behavior upon missing PWM remain bench test items. PCA9685 **OE must be held disabled during boot**, then explicitly enabled after initialization; determine inactive/dimmer fail-safe state experimentally. PCA9685 external `V+` servo rail is not needed for logic-only PWM connection.

### LCM relay wiring
| Logic source | Control | Relay board / intended function |
|---|---|---|
| OPi physical 8 PH2 | 3.3V GPIO proposed | ELEGOO 4-ch IN1: Shelly input-switch circuit 1 |
| OPi physical 10 PH3 | 3.3V GPIO proposed | ELEGOO 4-ch IN2: Shelly input-switch circuit 2 |
| OPi physical 12 PC11 | 3.3V GPIO proposed | ELEGOO 4-ch IN3: Shelly input-switch circuit 3 |
| OPi physical 16 PC15 | 3.3V GPIO proposed | ELEGOO 4-ch IN4: Shelly input-switch circuit 4 |
| MCP2 GPB0–GPB7 | 5V I/O | ELEGOO 8-ch IN1–IN8: eight relay outputs |

Both relay boards use 5V coil supply, active-low input scheme, built-in flyback devices; **GPIO 3.3V compatibility, optocoupler input loading and inactive boot state MUST be verified** before direct connection. Shelly AC-rated switch input behavior must be checked; all contact terminal groups on HV side, with proper creepage/clearance.

### 22 logical LCM outputs
- Relays: **A1–A8** (MCP2 GPB0–7)
- Analog PWM/0–10V: **10-1 … 10-10** (PCA9685 PWM0–PWM9)
- Shelly HV dimming: **HV-1/HV-2** = Shelly 1 `light:0/light:1`; **HV-3/HV-4** = Shelly 2 `light:0/light:1`
- Four GPIO-controlled ELEGOO relays are *Shelly wall-switch actuation contacts*, not four extra independent dimming channels. Optional third Shelly may later add HV-5/HV-6 only after changing schema and approved mappings.

### Internal managed switch — TP-Link TL-SG105E
| Port | Connected | VLAN20 | VLAN512 | PVID |
|---:|---|---|---|---:|
| 1 | Main house IoT network uplink | untagged | excluded | 20 |
| 2 | Orange Pi eth0 | untagged | tagged | 20 |
| 3 | Shelly dimmer 1 | excluded | untagged | 512 |
| 4 | Shelly dimmer 2 | excluded | untagged | 512 |
| 5 | future Shelly dimmer 3 | excluded | untagged | 512 |

OPi `eth0` = house VLAN20; `eth0.512` = private subnet 10.42.1.1/24 running interface-bound dnsmasq DHCP; no IP forwarding/routing to house IoT. Switch regulated 5V from branch, matching purchased revision connector/polarity. This assumes house uplink is VLAN20 **untagged** at port 1.

## 7. SIM (2U, Type B) field interface
- OPi Zero 3 1GB main header per §1. Type B panel POWER = regulated 3.3V rail (current-limited LED assembly); LINK = pin15/PC8; STATUS = pin16/PC15; FAULT = pin22/PC7; SPI1 display pins 19/21/23/24 plus LCD D/C pin11 and unmanaged reset line pin18; touchscreen I²C3 pins 3/5 with reset pin13; no MCPs solely for the panel.
- Main field supply **12V**; 5V control regulation as specified by the final SIM power design. FYSETC Hexa, three CAN zones feeding up to 18 RMC room clusters (12V / GND / CAN-H / CAN-L) in the established system concept. **No verified connector pin-by-pin Hexa schedule or finalized analog channel count is present in the agreed accessible material.** Do not invent GPIO, CAN transceiver, or ADC pin assignments.
- RMC sensor input fields, analog input physical terminals, 12V PSU exact selected part and Hexa board pin mapping: **TBD**. SIM's 2U chassis change supersedes historic 1U outline.

## 8. I²C address assignment and voltage domains
| Bus/device | Voltage side | Address/status |
|---|---|---|
| OPi I²C3 pins3/5 | native 3.3V | master |
| LCD touchscreen controller | 3.3V | address verify at bench |
| Bidirectional I²C level shifter LV | 3.3V | same bus |
| Bidirectional I²C level shifter HV | 5V | same bus |
| MCP1 | 5V | 0x26 proposed |
| MCP2 | 5V | 0x27 proposed |
| PCA9685 (LCM only) | 5V | 0x40 proposed |
| XL9535 relay card #1 (RCM) | 5V | 0x20 proposed |
| XL9535 relay card #2 (RCM) | 5V | 0x21 proposed |
| SIM Type B touch | 3.3V | no shifter for faceplate needed |
| HCM Jetson touch | 3.3V | Jetson pins 27/28 selected |

Physical bus topology is short daisy-chain SDA/SCL/GND; 5V logic supply daisy chains only devices with adequately rated power wiring; no relay-coil power via fine I²C daisy-trace. Pull-ups required on both sides of level translator; don't populate unnecessary multiple parallel pull-ups; actual board resistor values to be checked.

## 9. Open verification gates before crimping or energizing
1. **Selected LCD pin schematic**: power/logic, LCD D/C, reset, BL, TP INT and TP RESET must match exact Hosyond board. SPI1 Orange Pi overlay and Jetson SPI0/pinmux applied correctly.
2. **GPIO and 3.3V budget**: max LED current and display backlight from host 3.3V; identify alternate source if exceeding regulator current.
3. **Type A MCP placement**: confirm whether MCP1/MCP2 physically sit on front-panel PCB or control subassembly; calculate additional switch/LED/relay loom wires accordingly. 2×12 `J-FP1` is **provisional**, not a completed cable drawing.
4. **RCM bank selector**: define explicit 2×SPDT center-off physical throw-to-bank truth table consistent with software bank states.
5. **RCM contact commons**: shared COM1–COM8 distribution, max aggregate current, distinct circuit supplies, isolation and field connectors per intended loads.
6. **Relay ON/OFF**: hardware-level inactive state even on reboot, I²C failure or stuck GPIO; level conversion where required.
7. **Grounding**: protective earth to enclosure, separately document when DC negative is bonded; observe mains creepage/clearance and mains wiring regulations.
8. **SIM Hexa**: exact CAN/analog/field connector schedule cannot be finalized from current source; preserve as unresolved.
9. **Fire alarm**: reconcile final terminal wiring/polarity of both independent inputs before deployment. Safety-critical monitor operation should be tested on test bench without spurious real fire actions.

## 10. Reference documents / provenance
- Orange Pi official Zero 3 H618 user manual (26-pin and SPI chapter): https://orangepi.net/wp-content/uploads/2023/12/OrangePi_Zero3_H618_user-manual_v1.1.pdf
- Jetson 40-pin header: user-supplied expansion-header image in current chat.
- HCM baseline architecture outline `HCM_House_Control_Architecture_Outline.txt` (older than latest fire and enclosure revisions).
- Selected parts from user-provided Amazon/Shelly product screenshots in current chat; mechanical/electrical details to verify from the parts delivered.

# LCM Type A pin and output map

The authoritative complete inventory is `hardware_pins.yaml`. All physical
assignments are `UNVERIFIED`; real output paths remain disabled.

| Logical outputs | Physical mapping |
|---|---|
| A1-A8 | ELEGOO 8-channel relay board via MCP2 GPB0-GPB7 |
| 10-1 through 10-10 | PCA9685 at 0x40, PWM0-PWM9, PWM-to-0-10V converters |
| HV-1/HV-2 | Shelly 1, light:0/light:1 |
| HV-3/HV-4 | Shelly 2, light:0/light:1 |

PCA9685 PWM10-PWM15 are reserved. Four direct Orange Pi GPIO relay contacts
operate Shelly input-switch circuits and are not user-facing dimmer channels.
The 5V I2C side is behind the approved level shifter; the display/touch side
uses 3.3V I2C3 and SPI1.

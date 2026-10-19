# Hardware Driver Architecture

The production-intended drivers live in
`07_servises/common/physical_drivers.py`. They share transaction logic between
Linux transports and LAB1 mocks. The mock transport records every register or
RPC operation and can inject read, write, disconnect, and response failures.

## RCM

| Logical channels | Device | Address | Register model |
| --- | --- | --- | --- |
| A1-B8 | XL9535 | `0x20` | 16-bit output/configuration registers |
| C1-D8 | XL9535 | `0x21` | 16-bit output/configuration registers |

The channel index is zero-based internally: A1 is index 0 and D8 is index 31.
Outputs initialize high (relay off) and use active-low assertion. Updates are
serialized, preserve unrelated bits, and can verify output-register readback.

## LCM

| Logical channels | Driver | Address/identity | Mapping |
| --- | --- | --- | --- |
| A1-A8 | MCP23017 driver | manifest-defined `mcp2` (`0x27`) | GPB0-GPB7, active-low |
| 10-1..10-10 | PCA9685 driver | `0x40` | PWM channels 0-9, 1000 Hz contract |
| HV-1..HV-4 | Shelly RPC transport | `shelly_1`/`shelly_2` | `light:0`/`light:1` |

The four Shelly-control relay signals remain represented as a disabled
manifest capability and are not user-facing outputs.

## Front panel

`MockGPIOTransport` and `DebouncedInput` provide the shared input seam. The
current RCM bank selector remains authoritative through the existing module
state path; physical GPIO wiring and polarity are not electrically validated.

## LAB1

`build_lab1_mock_drivers()` instantiates the same production driver classes
with `MockI2CTransport`, `MockShellyTransport`, and `MockGPIOTransport`. It never
opens Linux devices or sends network RPCs. Module agents instantiate this bundle
only when their explicit mock-hardware profile requests it. Normal LAB1 and
production profiles keep commissioning and physical writes closed.

## Safety and commissioning

Driver construction is not authorization. A physical command must first pass
HCM logical routing, safety arbitration, authenticated module control, and the
module commissioning gate. `physical_output_enabled`, profile verification
status `COMMISSIONED`, a known channel in the authoritative output section,
and that section's `real_output_enabled` are required. Successful register or
RPC communication is reported as commanded state, never as proof of physical
actuation.

## Unverified items

Board voltage levels, bus topology, relay polarity under load, PCA9685-to-
0-10V electrical scaling, Shelly credentials/identities, input wiring, and
readback semantics require bench verification. No physical driver or output
test has been run in this milestone.

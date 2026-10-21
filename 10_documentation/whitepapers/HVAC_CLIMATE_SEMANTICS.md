# HCM native climate semantics

HCM exposes the existing thermostat authority as a logical `climate` entity.
The foundation entity is `climate.hcm_hvac`; its stable database identity is
owned by the `hcm_native` provider. State is reported in degrees Fahrenheit,
with a 0.5°F step and a 45–95°F range. Supported modes are `off`, `heat`,
`cool`, and `fan`.

`climate.set_temperature`, `climate.set_hvac_mode`, and `climate.turn_off`
create validated HVAC control requests. The policy gate checks fire and system
maintenance lockout before delegating to `HVACController`, which remains the
only authority for timing, interlocks, dampers, and physical outputs. Turning
off is allowed during a safety condition so it can reinforce a life-safety
shutdown. Requests expose requested and effective values in entity attributes;
the layer never calls GPIO, relays, or modules directly.

The service registry provides target and argument validation and supports
inspection and dry-run planning. HA climate services are translated by the
compatibility analyzer; actual entity identity still requires normal HCM
mapping. `climate.turn_on`, preset, fan, and auxiliary HVAC services remain
unimplemented until their measured semantics are designed.

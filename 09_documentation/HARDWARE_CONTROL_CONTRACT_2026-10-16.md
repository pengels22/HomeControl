# HomeControl Hardware Control Contract

## Authority

Web and native touchscreen commands use the same HCM logical command authority:
`command_logical()` -> safety arbitration -> authenticated module control
session. Physical channel identifiers are resolved by HCM/module configuration;
clients do not address hardware directly.

The isolated touchscreen preview remains local and simulated when
`HOMECONTROL_HCM_API_URL` is unset. When it is set, the touchscreen adapter
forwards commands to HCM and does not fall back to local state if HCM is
unavailable. A logical binding must be supplied by
`HOMECONTROL_TOUCHSCREEN_LOGICAL_MAP` (for example, `RCM:A1`); missing bindings
are rejected.

## Physical safety gate

`SIMULATED` is the default. `PHYSICAL_BENCH` is descriptive only and never
authorizes a write. A normal physical write requires all of the following in
the hardware manifest:

1. verification status `COMMISSIONED`.
2. `physical_output_enabled: true`.
3. The requested channel exists in the authoritative output section.
4. The output section's `real_output_enabled: true`.

Environment variables, touchscreen settings, and command payloads cannot enable
commissioning. Current RCM and LCM manifests are non-commissioned, so physical
writes remain disabled. Durable binding metadata may select
`execution_mode: physical`; HCM translates that to its wire flag, while the
module independently enforces this gate. The default is `simulated`.

`BENCH_TESTING` is accepted as a lifecycle state but is rejected by normal
module commands. Only the opt-in `12_hardware_tests` harness may authorize one
exact module/channel target during a separately approved hardware test.

## Active hardware contracts

The active design contracts are XL9535 relay cards for RCM and PCA9685 plus
Shelly Pro Dimmer 2PM mappings for LCM. Older MCP23017/MCP4725 references are
legacy documentation only and remain recorded in
`architecture/HCM_HARDWARE_MAP.md`; they must not be used to infer pinouts.

The current adapters are discovery-only or mocked. No bus write, GPIO write,
Shelly request, or commissioning test is included in this milestone.

## Verified update artifacts

Module update requests carry signed artifact metadata only. HCM and the module
update service verify the target module, hardware revision, SHA-256 digest and
Ed25519 signature before execution. The installer is selected from a fixed
per-module registry; executable paths and argument arrays supplied by a client
are rejected. Update execution remains disabled unless deployment config
explicitly enables the already-verified service path.

The systemd service reads `/etc/homecontrol/update-service.env` for the target
module, hardware revision, public-key file, request-secret file, bind address,
port, staging root, and explicit execution enable flag. Requests use the
existing HCM shared-secret HMAC mechanism as a transitional authenticated
transport boundary; mTLS integration remains a separate deployment task. Each
operation ID is timestamp-checked and accepted only once.

## Commissioning prerequisite

Before any output test, verify board identity, bus/address/polarity, supply
levels, emergency behavior, and independent meter/load isolation. Then approve
one channel explicitly and perform the RCM A1 procedure under the hardware
commissioning runbook. This milestone stops before that procedure.

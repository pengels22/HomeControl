# HomeControl Full-System Audit

Date: 2026-10-17  
Branch: `feature/hardware-integration-config-logging`  
Audit baseline: `03c8b16ef7b97fe38960ed6a3bb5714c0ccad43b`

## Scope and method

This was a read-only architecture, safety, hardware-driver, deployment, and test-quality audit. No live host, module, database, service, firmware, GPIO, or physical output was changed. The audit inspected the repository, manifests, code paths, tests, and documentation. It did not claim live HCM, Conflict, LAB1, or physical-bench verification.

## Executive result

The repository has a sound HCM-authoritative logical command model and explicit simulation/output inhibition controls, but it is not ready for physical output commissioning. The highest risks are two production-driver register/protocol defects, a native touchscreen authority gap, and the fact that the default HCM startup does not select the manifest-driven physical fire-input reader.

No confirmed CRITICAL finding was identified in the repository audit. The highest findings are HIGH and must be resolved before physical commissioning or production touchscreen control.

## Findings

### HIGH-1: MCP23017 LCM relay driver selects the wrong port

`07_servises/common/physical_drivers.py` uses `IODIR=0x00` and `OLAT=0x14`. The active LCM manifest declares `MCP2_GPB0_GPB7` in `06_config/03_LCM/hardware_pins.yaml`, while the MCP23017 default BANK=0 register map places Port B at IODIRB `0x01` and OLATB `0x15`. The driver does not select BANK=1. Its initialization and relay writes therefore target Port A, which is reserved by the module infrastructure for selector inputs/front LEDs.

The MCP23017 datasheet documents the BANK-dependent register map: [Microchip MCP23017 datasheet](https://ww1.microchip.com/downloads/aemDocuments/documents/OTH/ProductDocuments/DataSheets/20001952C.pdf).

Impact: a future physical commissioning could configure or write the wrong expander port. Current tests use permissive mocks and current output gates keep physical writes disabled. Fix requires an explicit register-map model, Port B writes, preservation of Port A, and hardware bench verification.

### HIGH-2: PCA9685 dimmer driver programs frequency and PWM fields incorrectly

`07_servises/common/physical_drivers.py` writes `MODE1=0`, then writes `PRE_SCALE` without putting the device into sleep. It writes the raw brightness value into the LED channel ON count rather than using normal ON=0/OFF=`raw`, and does not explicitly configure the output mode or use the full-off behavior for zero. The mock transport accepts the sequence, so existing tests do not establish device correctness.

The PCA9685 datasheet requires the sleep/program/wake sequence for `PRE_SCALE` and defines the LED ON/OFF counter fields: [NXP PCA9685 datasheet](https://www.nxp.com/docs/en/data-sheet/PCA9685.pdf).

Impact: physical dimmer output behavior is unverified and may be incorrect. Keep outputs disabled until the driver is corrected and tested against a register-aware mock and hardware instrument.

### HIGH-3: Native touchscreen defaults to a local simulated command path

`10_scripts/touchscreen_native.py` constructs a local API client using `http://127.0.0.1:8765` unless an environment URL is supplied. The native application therefore uses local touchscreen state/command endpoints and has no injected authenticated HCM client or logical-binding authorization context. `10_scripts/touchscreen_app.py` also selects simulation when the HCM API URL is absent.

This is suitable for the isolated bench preview but is not an acceptable implicit production control path. The production adapter must require authenticated HCM authority, preserve logical identity, and fail closed when HCM is unavailable. No live touchscreen deployment was performed.

### HIGH-4: Default HCM startup does not select the physical fire-input reader

`01_HCM/main.py` instantiates `HCMSafetyRelayController()` in its default startup path. The manifest-driven Linux GPIO implementation exists in `01_HCM/safety_relays.py` through `from_linux()`, but the default path does not select it. Consequently, the repository contains the intended reader and safety routing, but physical HCM fire sensing is not active by default.

This is a safe incomplete state rather than a reason to activate it automatically. Wiring, pinmux, electrical polarity, debounce, maintenance-lockout behavior, and supervised fault behavior require explicit physical verification before selection.

### MEDIUM-1: Dashboard fire status does not map published safety inputs

Heartbeat publication includes `status.safety_inputs` in `00_Heartbeat/hcm_heartbeat.py`, but `01_HCM/management.py` dashboard status assembly does not map that data into the dashboard health fields consumed by `01_HCM/www/app.js`. The dashboard can therefore show Unavailable even when an authenticated source has published sensor data.

The repair should expose freshness-checked sensor state and health independently, with Unknown/Fault preserved. It must not infer a healthy fire state from missing data or combine HCM and Conflict into an unverified consensus.

### MEDIUM-2: Hardware mocks are not protocol-aware

`MockI2CTransport` accepts arbitrary register operations and echoes values. `MockShellyTransport` accepts broad calls without validating the production component/schema contract. Existing tests mainly assert that operations occurred. These mocks can pass an incorrect production register sequence.

Add strict MCP23017 and PCA9685 register models, active-low expectations, masks, preserved bits, reset behavior, and a strict Shelly command schema before relying on mock results for commissioning readiness.

### MEDIUM-3: HCM has a development database fallback

`01_HCM/settings.py` contains a fallback database URL with development credentials. Environment configuration can override it, but non-development startup does not appear to reject the fallback. Production startup should require an injected secret and fail closed when it is absent.

### MEDIUM-4: Module `/health` exposes detailed information without authentication

`07_servises/common/agent.py` exposes identity, faults, configuration revision, pending delivery, and recent logs from the unauthenticated `/health` route. This is not a command-write bypass, but it increases information exposure on a module service bound to a network interface. Restrict or minimize the route after confirming the emergency-health contract, and keep detailed diagnostics authenticated.

### MEDIUM-5: LCM physical output implementation is incomplete outside mock mode

`03_LCM/main.py` creates production-shaped drivers for mock hardware, while normal real mode does not yet provide a complete commissioned driver bundle. The logical A1 path is in-memory in the inspected startup code. This is safe while outputs remain disabled, but incomplete for physical deployment.

## Safety and control assessment

- The intended web/API path is HCM-authoritative: authenticated request, logical binding lookup, `command_logical()`, arbitration, registry module session, and module-local safety/commissioning checks.
- Fire alarm state is routed through the existing safety controller; AC-power absence is not treated as a fire event.
- Maintenance lockout remains higher priority than convenience output commands in the tested software path.
- HCM and Conflict fire-input identifiers, polarity, and 250 ms debounce are represented in the manifests and independent readers.
- Physical outputs are disabled by default and commissioning is not enabled by the repository tests.
- The native touchscreen is the exception that requires an explicit authenticated HCM adapter before production use.
- Physical feedback is primarily commanded-state reporting; it should not be represented as verified electrical state without device telemetry.

## Communication, authentication, and deployment assessment

The repository contains HMAC verification for Conflict responses and timestamp/supervision handling, but this audit did not perform a live authenticated exchange. Clock-skew, replay, duplicate, stale-acknowledgment, and reconnect behavior should be exercised against an isolated integration pair before release.

Deployment tooling includes target checks, dry-run support, backups, and rollback references. No deployment or live-host connection was attempted for this audit. The current documentation contains historical network and host references that should be marked explicitly as superseded; in particular, older HCM/Orange Pi and VLAN references conflict with the current Jetson/VLAN 20 development deployment.

The Conflict manifest is JSON-compatible despite its `.yaml` suffix and is read with `json.load`; this currently works for the checked-in file but is brittle and would fail if ordinary YAML were introduced. Legacy MCP23017/MCP4725 references also remain alongside the active PCA9685/Shelly design and should be labeled as historical.

## Test evidence

Executed from the repository:

```text
./.venv/bin/pytest -q
482 passed, 9 skipped, 1118 warnings

./.venv/bin/python -m compileall -q 00_Heartbeat 01_HCM 02_SIM 03_LCM 04_RCM 05_PNL 06_config 07_servises 10_scripts 11_tests
PASS

git diff --check
PASS
```

The warnings were existing deprecation warnings. No live hardware, physical transport, HCM, Conflict, LAB1, Jetson, database, or module service was modified during this audit.

## Prioritized remediation

1. Correct and strictly test MCP23017 Port B register access.
2. Correct PCA9685 sleep/prescale/PWM sequencing and zero/full-off behavior.
3. Make the production native touchscreen require authenticated HCM authority and logical bindings.
4. Complete the explicit, verified physical HCM fire-input startup path.
5. Add dashboard safety-input mapping with freshness and Unknown/Fault semantics.
6. Harden mocks, production secret requirements, and unauthenticated module diagnostics.
7. Remove or label superseded documentation and legacy hardware references.

## Audit conclusion

The software is suitable for continued simulated testing and isolated mock validation. It is not ready for physical output commissioning or unattended native touchscreen control until HIGH-1 through HIGH-4 are resolved and independently verified. This report intentionally makes no code or live-system changes.

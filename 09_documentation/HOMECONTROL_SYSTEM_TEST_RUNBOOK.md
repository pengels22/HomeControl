# HomeControl Unified System Test Runbook

Status: repository implementation only. This runbook does not authorize live execution.

## Purpose

`10_scripts/homecontrol_system_test.py` is the device-hosted coordinator for one
bounded HomeControl system test. It produces one correlated report directory:

- `report.html`
- `report.json`
- `report.txt`
- `detailed-results.json`
- `test-manifest.json`
- `sanitized-diagnostics.json`

The coordinator separates live read-only diagnostics from isolated mutating
scenarios. Mutating scenarios use the existing production-shaped drivers with
mock I2C, Shelly and GPIO transports. No real GPIO, I2C, SPI or Shelly output
transport is selected by this framework.

## Local fixture validation

From the repository root:

```sh
./10_scripts/homecontrol-system-test --fixture \
  --report-dir /tmp/homecontrol-system-test
```

Fixture mode is expected to return exit code `2` because live device diagnostics
are marked `SKIP` and the overall result is therefore `INCOMPLETE`. It still
executes the isolated HCM authority, PIN/session, driver, debounce and cleanup
scenarios and writes all five reports. `--inject-failure` verifies nonzero
failure reporting and is only for framework tests.

## Device-hosted execution

Install the repository on the authorized HCM test host using the existing
deployment process. Do not alter a service definition or enable a persistent
agent. Run the coordinator as a transient process or transient systemd unit so
an SSH disconnect does not terminate it, for example:

```sh
sudo systemd-run --unit=homecontrol-system-test-$(date +%s) \
  --collect --wait \
  /path/to/repository/10_scripts/homecontrol-system-test \
  --full --report-dir /var/log/homecontrol/system-tests
```

The coordinator uses the repository's strict SSH aliases (`jetson`, `conflict`,
`lab1`) and fixed read-only commands for host identity, UTC time, service
status, and disk space. Host keys and existing authentication remain required.
It does not issue remote service restarts, clock changes, network changes,
output commands, role changes, database writes, or fire actions.

`--skip-remote` is useful only for a local rehearsal of the coordinator and
marks live diagnostics `SKIP`; it must not be reported as a complete system
verification. A run-level lock prevents concurrent runs. The timeout is bounded
(`--timeout` defaults to 300 seconds), and SIGINT/SIGTERM cause remaining
steps to be marked `BLOCKED` while the report is still written.

## Scope and interpretation

Subsystem records cover HCM/API, Conflict/device diagnostics, RCM/LCM driver
paths, SIM/RMC inputs, native touchscreen authority, PIN permissions, security,
heartbeat/readiness and commissioning gates. `PASS` means the specific software
or read-only check passed. `SKIP` and `BLOCKED` never count as `PASS`.

The report always lists electrical commissioning, physical relay/dimmer
behavior and actual fire wiring as unverified. A successful software/integration
run is not physical commissioning approval.

## Access and deployment prerequisites

- Authorized SSH aliases and strict known-host keys for HCM, Conflict and LAB1.
- Read-only diagnostic access to the three devices.
- Writable report directory with controlled permissions.
- Existing repository checkout and Python runtime.
- No production database credentials are required by the fixture harness.
- No touchscreen PINs, device tokens, private keys or secrets are passed to the
  coordinator or written to reports.

If a device is unavailable or a safety prerequisite cannot be independently
verified, the result must remain `BLOCKED`; do not bypass the gate or substitute
a test flag for output inhibition evidence.

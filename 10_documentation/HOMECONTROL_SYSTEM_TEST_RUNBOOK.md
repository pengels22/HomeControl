# HomeControl Unified System Test Runbook

Status: repository implementation only. This runbook does not authorize live execution.

## Purpose

`11_scripts/homecontrol_system_test.py` is the coordinator for one bounded
HomeControl system test. It can run on the MacBook or on an authorized device
in the future. Each run produces one correlated report directory:

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
./11_scripts/homecontrol-system-test --fixture \
  --report-dir /tmp/homecontrol-system-test
```

Fixture mode is expected to return exit code `2` because live device diagnostics
are marked `SKIP` and the overall result is therefore `INCOMPLETE`. It still
executes the isolated HCM authority, PIN/session, driver, debounce and cleanup
scenarios and writes all five reports. `--inject-failure` verifies nonzero
failure reporting and is only for framework tests.

The fixture also generates a communications matrix, concurrent synthetic HCM
and Conflict workloads, latency percentiles, throughput, ACK/missed-ACK counts,
clock-skew fields, and a time-series resource sample. Use
`--inject-supervision-failure` to verify that synthetic ACK loss aborts both
workloads and produces a nonzero result. These workloads never open sockets.

## MacBook-hosted initial execution

The MacBook is the preferred coordinator while it is the only host authorized
to SSH to all three processors. Run from the repository root with the existing
SSH aliases and strict known-host configuration:

```sh
./11_scripts/homecontrol-system-test --full \
  --timeout 900 --stress-duration 600 --stress-concurrency 4 \
  --report-dir ./system-test-reports
```

This command performs local coordination, direct read-only SSH diagnostics to
`jetson`, `conflict`, and `lab1`, and authenticated read-only HCM registry
discovery when credentials are supplied. It does not assume Jetson-to-device
SSH access and does not use the MacBook as a production-control proxy. It does
not require root, `systemd`, Linux-only resource APIs, or a graphical session.
The local stress workload is synthetic and isolated; remote CPU, memory,
temperature, time, service, and supervision samples are reported separately.

For a terminal-independent MacBook run, create the local report parent and use
the normal macOS process launcher:

```sh
mkdir -p ./system-test-reports
nohup ./11_scripts/homecontrol-system-test --full \
  --timeout 900 --stress-duration 600 --stress-concurrency 4 \
  --report-dir ./system-test-reports \
  > ./system-test-reports/launcher.log 2>&1 &
echo $!
```

The expected maximum runtime is approximately 15 minutes: initialization,
read-only diagnostics, the 600-second isolated workload, cleanup, and report
generation all share the 900-second deadline. Each invocation creates a unique
UTC-named child directory. Set `HC_SYSTEM_TEST_HCM_URL` and
`HC_SYSTEM_TEST_HCM_TOKEN` only in the process environment when an approved,
short-lived read-only HCM token is available; never put credentials in the
command line or reports. Without them, the live registry matrix remains
`BLOCKED` by design.

Before the first operational run, verify that each alias resolves to the
expected host identity and that its SSH key is already trusted. The first full
run is separately authorized; this repository change has not contacted live
hosts. Live high-rate stress remains `BLOCKED` unless separately approved.

## Device-hosted execution

Install the repository on the authorized HCM test host using the existing
deployment process. Do not alter a service definition or enable a persistent
agent. Run the coordinator as a transient process or transient systemd unit so
an SSH disconnect does not terminate it, for example:

```sh
sudo systemd-run --unit=homecontrol-system-test-$(date +%s) \
  --collect --wait \
  /path/to/repository/11_scripts/homecontrol-system-test \
  --full --report-dir /var/log/homecontrol/system-tests
```

The coordinator uses the repository's strict SSH aliases (`jetson`, `conflict`,
`lab1`) and fixed read-only commands for host identity, UTC time, service
status, and disk space. Host keys and existing authentication remain required.
It does not issue remote service restarts, clock changes, network changes,
output commands, role changes, database writes, or fire actions.

The live matrix discovers registered modules through the authenticated,
read-only HCM `/api/v1/modules` endpoint when `HC_SYSTEM_TEST_HCM_URL` and a
short-lived `HC_SYSTEM_TEST_HCM_TOKEN` are supplied in the transient unit's
environment. It tests only registered module addresses and port 6501; it does
not scan arbitrary ports. Without those variables the matrix is `BLOCKED`.
The bearer token is never written to reports.

`--stress-duration` accepts 1-600 seconds and defaults to the requested
ten-minute maximum. `--stress-concurrency` defaults to four workers and is
bounded at sixteen. In fixture mode the duration is capped to a short run so
developer validation does not wait ten minutes. The default full command
records live high-rate stress as `BLOCKED`; an authenticated read-only live
stress adapter requires a separate explicit approval and endpoint contract.
No heartbeat traffic is generated by this repository implementation, and the
active HCM/Conflict supervision path is never used as a load target.

`--skip-remote` is useful only for a local rehearsal of the coordinator and
marks live diagnostics `SKIP`; it must not be reported as a complete system
verification. A run-level lock prevents concurrent runs. The timeout is bounded
(`--timeout` defaults to 900 seconds, including initialization, diagnostics,
stress, cleanup and report generation), and SIGINT/SIGTERM cause remaining
steps to be marked `BLOCKED` while the report is still written.

Every invocation creates a unique report directory below `--report-dir`, named
with the UTC start timestamp and run ID. The device-hosted default is therefore
`/var/log/homecontrol/system-tests/hc-system-<timestamp>-<id>/`.

Before mutating simulation scenarios, the coordinator reads installed-state
evidence from the target hosts. LAB1 must report its expected device identity,
`simulation=true`, `physical_outputs_enabled=false`, and an empty commissioning
allowlist. HCM and Conflict must return their installed service/configuration
evidence. Missing or ambiguous installed-state evidence blocks applicable
scenarios; repository manifests alone are insufficient.

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

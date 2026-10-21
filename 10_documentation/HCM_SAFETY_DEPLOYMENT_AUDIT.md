# HCM safety route and deployment audit — 2026-10-19

Starting revision: `e6d1963818ba13bbfe76163fd2039712878ff074`.
Scope: repository changes and offline tests only. No SSH, live container changes,
GPIO reads, output commands, or Conflict runtime changes were performed.

## Route and dashboard

`01_HCM/api.py` defines `GET /safety/status` on the `/api/v1` router.
`01_HCM/main.py` constructs the production FastAPI application and includes
`api.router` before mounting `/static`. The remaining HTML routes do not overlap
`/api/v1/safety/status`. Tests instantiate this actual application without its
lifespan, inspect its generated OpenAPI route table, and issue HTTP requests.
OpenAPI inspection handles both flattened and lazy included-router FastAPI versions.

The unauthenticated result is 401; a READONLY authenticated user receives 200
when SafetyController is configured, or 503 if it is absent. The response is
`{'ok': True, **safety.status_payload()}` and includes status, system_state,
fire_active, maintenance_lockout_active, physical_input_authoritative,
fire_alarm_s, and fire_alarm_P. It does not consult the module registry.

The dashboard calls `api("/safety/status")`, which uses `/api/v1`, independently
of registry results. Normal shows Normal; Active shows FIRE ACTIVE; Unknown now
remains Unknown with Physical input and unknown input detail. API absence/failure
shows Unavailable. Explicit simulation is labelled Simulation.

## Deployment and the reported 404

The Jetson adapter builds `07_config/01_HCM/Dockerfile.live` from the extracted
`git archive` release root at `/tmp/homecontrol-release-<SHA>` and tags it
`homecontrol-hcm:<SHA>`. It copies requirements then the entire release root,
including `01_HCM/api.py` and `01_HCM/www`, into `/opt/HomeControl`. It launches
`python -m uvicorn 01_HCM.main:app --host 0.0.0.0 --port 8080`.
The root Dockerfile/compose files are not this installed-host deployment path.
No database migration is needed for these changes.

A Git update does not alter image layers or recreate `hcm-test`. The old helper
accepted a health-only check, and the framework's no-change path trusted a release
marker plus health. Thus an old image can remain healthy while lacking this route.
This is a concrete stale-deployment mechanism, **not proof of the exact live 404
cause**: identifying the live image, launch override, or proxy requires a later
approved inspection. The source has no shadowing route to explain a 404.

The build now requires a full `HCM_GIT_SHA` argument. It writes non-secret
`01_HCM/build_info.json` with version, SHA, and UTC build time, then verifies the
actual app route table and both copied source assets during image construction.
`GET /api/v1/version` is public and returns this file, independent of `.git` or
stale environment values inherited when cloning the previous container.
Source-only execution truthfully returns unknown build identity.

The deployment helper requires `--expected-sha`; after replacement it verifies
SHA, health, unauthenticated safety route 401, and served static JS. Failure uses
the existing original-container recovery flow and exits unsuccessfully. A matching
release marker on the no-change path now also requires matching runtime SHA.
A source sync alone is not an HCM deployment; use the reviewed deployment adapter.

After a separately approved deployment, the read-only verification command is:

```sh
python3 11_scripts/hcm_verify.py --url http://192.168.20.27:8080 --expected-sha <full-release-SHA>
```

Without `--url`, the verifier checks an image's files, metadata and actual app
registration using explicit simulation and without lifespan or hardware access.
CI builds the fresh image and runs this check with networking disabled. Local
Docker is unavailable; actual image verification therefore depends on that CI step.
The runtime verifier only reads cached SafetyController status, never samples GPIO.

## Authority and physical input findings

HCM defaults to `HCM_SAFETY_INPUT_BACKEND=linux`. The physical path is
`HCMSafetyRelayController.from_linux()` -> `LinuxSafetyInputBackend` ->
`LinuxGPIOInputTransport`. A misplaced physical-authority class attribute was
corrected: the Linux backend now owns it. This also prevents software fire
simulation from overriding the physical input.

Initialization failure previously aborted import/startup. It now installs an
unavailable physical-input backend that returns unknown values and rejects writes.
It never selects simulation. Partial GPIO initialization closes already opened
inputs. Sampling/read faults report Unknown, and physical authority remains true.
Repairing an initialization fault requires an approved HCM restart; no automatic
simulation or hardware retry was added. Runtime sampling continues to report
faults through the existing safety reporter.

FIRE wiring remains NO -> 3.3 V, C -> GPIO, NC -> GND, normal LOW, alarm HIGH,
250 ms debounce. Jetson FIRE is header pin 38 / gpiochip0 line 159; AC-present is
separate, header pin 40 / gpiochip0 line 158. AC loss is not a fire event.
HCM owns fire state, HVAC force-off, emergency-light orchestration and API/UI.
Maintenance priority, physical output gates and HVAC timing are unchanged.
Installed GPIO permissions, device mounts and physical wiring remain unverified.

## Conflict: C supported; independent GPIO disabled in checked-in configuration

`00_Heartbeat/gpio_inputs.py` supports independently reading/debouncing Conflict's
own fire and AC contacts. `config-conflict.json` sets `gpio_inputs.enabled=false`.
The manifest specifies header pins 38/40, gpiochip1 lines 260/259. No assertion
is made that the installed configuration or physical contacts have been validated.

HCM's `SafetyHeartbeatReporter` sends status/fault messages to the local host
Heartbeat control socket. Heartbeat carries those as `status.modules` and health
faults, and Conflict retains peer status under its device-ID-keyed registry.
Conflict's own contacts are separately exposed as `status.safety_inputs`; HCM's
reported fire values are under `status.registry[HCM-device-id].status.modules`.
They are not merged into one fire value. Disabled/unavailable contacts remain
unknown. Delivery depends on the existing control socket and authenticated peer
transport being available; repository code is not proof of installed connectivity.
Conflict supervises peers/communications; it does not run HCM HVAC or lighting
orchestration. No second HCM application authority was introduced.

## Repository-wide occurrence classification

`FIRE_AUTHORITY_OCCURRENCES.tsv` inventories every matching line and the count of
each requested search term (case-insensitive, including overlapping terms), by
component. Regenerate with `python3 11_scripts/audit_fire_authority.py`; the inventory
excludes itself. Broad `fire` matches include non-safety words such as firewall.

- HCM: physical inputs, authority, safety arbitration/orchestration, API/UI.
- Heartbeat: independent contact monitoring, status/fault propagation and supervision.
- RCM/LCM/SIM: only `fire_input_fault` conditions in local safe-off handling;
  no physical fire detector, global fire publisher or SafetyController.
- PNL: no matching fire authority implementation.
- Shared services: reusable input/debounce and arbitration primitives; priority
  tokens describe commands and conditions, not an independent module detector.
- Configuration/manifests: component-specific input definitions and deployment policy.
- Database: persistent events and arbitration metadata; no new authority or migration.
- Tests/tooling: simulated inputs, explicit HIL gates, preview fixtures and checks.
- Documentation: architectural and historical references, not active implementations.

The white paper's older phrase “RCM fire-input fault” describes a supplied safe-off
condition; it does not mean RCM senses an authoritative fire input.

## Local validation

Python 3.14.7 in the existing repository virtual environment; all tests run with
`HCM_SAFETY_INPUT_BACKEND=simulated` to prohibit physical access. The physical
failure tests use fake transports and explicitly select Linux behavior.

- Focused route/safety/GPIO/deployment tests: 119 passed.
- Full `python -m pytest`: 562 passed, 10 skipped.
- Requested compileall directories, including `13_hardware_tests`: passed.
- `node --check 01_HCM/www/app.js`: passed.
- `git diff --check`: passed.
- Deprecation warnings remain from the existing Python/pytest-asyncio dependencies.

Hosted CI and its fresh image-build result must be checked against the exact
resulting commit before classifying this change ready for reviewed redeployment.

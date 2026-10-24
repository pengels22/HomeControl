# Pass 1 Report — Finish Current HCM Work

Date: 2026-10-24
Repository: `pengels22/HomeControl`

## Result

Pass 1 is complete for the current HCM/Matter scope. The existing Checkpoint 1–7
work was reconciled against the source tree and authoritative documentation. A
live NWS recovery defect was fixed and covered by regression testing. No SIM/RMC
deletion, PNL firmware work, hardware change, live deployment, or physical I/O
test was performed as part of this pass.

## Change log

- `01_HCM/weather_service.py`
  - Canonicalizes coordinates with more than four decimal places before NWS
    point lookup, avoiding the NWS precision redirect that the bounded HTTP
    client intentionally does not follow.
  - Re-fetches point metadata when a cached record lacks a forecast URL instead
    of treating an incomplete cache as valid forever.
- `12_tests/test_weather_service.py`
  - Adds coverage for coordinate canonicalization and recovery from incomplete
    point cache data.
- `10_documentation/PNL_MIGRATION_BASELINE.md`
  - Records source state, architecture inventory, risks, and carry-forward
    decisions for the six-pass PNL migration.

## Validation

Focused affected suite:

```text
85 passed, 14 skipped
```

The focused selection covered native weather/API behavior, database migrations,
Areas, canonical entities, and metadata persistence. The initial run exposed the
existing test expectation for coordinate formatting; the implementation was
adjusted to preserve already-valid short coordinates while canonicalizing only
over-precise values, and the focused suite then passed.

Final validation gates:

- Full pytest suite: **829 passed, 46 skipped, 2495 warnings**.
- Python compileall: passed.
- JavaScript syntax validation (`bridge.mjs`, `app.js`): passed.
- `git diff --check`: passed.
- Migration/configuration coverage: the migration and metadata integration tests
  passed in the focused and full suites; no live migration or configuration
  mutation was performed for this Pass 1 code change.

## Pass 2 prerequisites

Pass 2 may begin only after this commit is available remotely and the following
are explicitly reviewed:

1. A complete SIM/RMC dependency matrix covering imports, runtime manifests,
   services, configuration, database records, UI/API paths, updater/rollback,
   safety behavior, and separately running nodes.
2. A reversible retirement migration design that preserves historical records,
   audit events, mappings, and rollback compatibility.
3. Focused proof that current RCM, LCM, HCM, ACM, Heartbeat, and safety behavior
   does not depend on the legacy paths selected for retirement.
4. A disposable database forward/rollback test plan and explicit hardware/HIL
   boundary. No live SIM/RMC deletion is implied by this report.

## Rollback

Revert the Pass 1 commit to restore the prior NWS coordinate/cache behavior. The
change does not alter database schema, Matter storage, endpoint allocation,
module protocol, safety arbitration, deployed services, or hardware state.

## Remaining scope

The next pass is SIM/RMC retirement analysis and implementation. PNL backplane,
ESP32-P4 firmware, dashboard editor backend, and browser editor remain deferred
to Passes 3–6.

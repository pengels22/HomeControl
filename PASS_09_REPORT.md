# Pass 9 — Consolidation, Jetson deployment preparation, and PNL display

## Implemented

- Added one bounded, ordered HCM PNL state-event publisher and dashboard publish
  notifications, with panel resynchronization limits.
- Completed editor card selection, movement, resizing, removal, entity binding,
  area-filtered catalog loading, and PNL assignment administration UI.
- Added explicit PNL retention policy and dry-run maintenance tooling.
- Added a shared native-style PNL display engine with local aliases, themes,
  last-known-good fallback, remote unavailable states, and independent frame
  geometry.
- Replaced the first-pass PNL webpage with a full-width 1024×600 desktop preview
  containing header connectivity/microphone status and all core environmental,
  lighting, and thermostat fixture regions.
- Extended the ESP-IDF scaffold with independent task boundaries without
  inventing board GPIO or claiming hardware validation.
- Added deployment, legacy cleanup, hardware bring-up, and validation reports.

## Validation

The focused Pass 9 suite passed 18 tests. The complete suite passed **860
tests with 46 skipped before the final legacy-policy test; the final focused
legacy-policy test also passed. Python compileall, JavaScript syntax validation, and
`git diff --check` also passed.

## Deployment status

The authorized software preparation is complete. A read-only SSH preflight now
succeeds: the deployed HCM is healthy, Heartbeat V3 and the HCM-only watchdog
are active, Conflict is online, and the Ethernet-first route is present. The
host is still running the prior HCM container SHA with migrations through 025;
Pass 9 migrations 026–029 and the new container remain pending. No live host or
physical output was changed.

## Remaining limitations

State publication hooks for every existing HCM producer, real PostgreSQL
disposable integration, ESP-IDF compilation, physical board bring-up, and final
SIM/RMC deletion remain separate gates documented in the companion reports.

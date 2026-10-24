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

The Pass 9 Jetson deployment completed after explicit approval. A fresh
PostgreSQL backup was restore-tested in an isolated PostgreSQL 16 container;
migrations 026–029 applied successfully. Deployment ID
`hc-20261024T1330Z-84f9f3f3` now runs release SHA
`84f9f3f340bb0fd47108245546fbf121c267d4dd`, with the prior container retained
for rollback. HCM health/version, PNL/editor authentication gates, mounted
storage and PKI, watchdog, Heartbeat V3, and Conflict supervision all passed.
No physical output operation was performed.

## Remaining limitations

State publication hooks for every existing HCM producer, real PostgreSQL
disposable integration, ESP-IDF compilation, physical board bring-up, and final
SIM/RMC deletion remain separate gates documented in the companion reports.

# Pass 8 integration results

The production router and models were exercised with focused FastAPI contract
tests and the existing deterministic three-panel simulator. The focused suite
covered route separation, MAC normalization, fail-closed panel authentication,
bounded command/occupancy payloads, dashboard validation, telemetry replay, and
the Pass 7 concurrent panel scenarios.

Result: **17 focused tests passed** before final validation. The complete suite
passed with **853 passed, 46 skipped**.

Disposable PostgreSQL integration was not available because
`HCM_TEST_DATABASE_URL` is unset in this environment. Migration ordering and
schema-contract tests still passed; no live database or host was modified.

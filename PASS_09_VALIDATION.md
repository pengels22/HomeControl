# Pass 9 validation

## Software checks

- Focused PNL display, retention, event, editor, and API tests: 18 passed.
- Full pytest suite: 860 passed, 46 skipped.
- Python compileall and JavaScript syntax checks: required final gates.
- Migration ordering/schema checks: migration 029 included; no live database
  migration was run.
- `git diff --check`: required final gate.

## Blocked checks

- Disposable PostgreSQL integration: no `HCM_TEST_DATABASE_URL` was configured.
- Jetson runtime and backup/restore: SSH authentication failed.
- ESP-IDF build: `idf.py` environment unavailable.
- Hardware/HIL, live outputs, physical sensors, audio, and touchscreen: not
  authorized or physically available.

All simulator and display results are software evidence only. They do not prove
embedded LVGL or field installation readiness.

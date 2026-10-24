# Pass 5 Report — Dashboard Editor Backend

Date: 2026-10-24

## Result

Pass 5 adds the HCM dashboard editor backend foundation. Layouts are persisted
as bounded revisions, validated with the same interpreter contract used by PNL,
previewed without actions, published atomically, and reverted through a new
revision. Draft updates and publish/revert operations require an expected
revision, preventing silent concurrent edit loss.

## API surface

- `POST/GET /api/v1/dashboard-editor`
- `PUT /api/v1/dashboard-editor/{id}/draft`
- `GET /api/v1/dashboard-editor/{id}/preview`
- `POST /api/v1/dashboard-editor/{id}/publish`
- `POST /api/v1/dashboard-editor/{id}/revert`

All routes require existing HCM authentication. Layout validation rejects
arbitrary scripts/HTML/CSS, unsupported card types, invalid geometry, malformed
pages, and excessive card/page counts. Preview responses are explicitly marked
`preview_only` and contain no command execution path.

Migration `028_dashboard_editor.sql` adds document, revision, and assignment
records. Assignment rows are ready for panel/area resolution in Pass 6; failed
publish leaves the previous published revision untouched.

## Pass 6 prerequisites

The browser editor should use these APIs and the Pass 4 schema, preserve
optimistic revision conflicts, show last-good published state, and keep Sonic
mute immutable in the preview. It must not create a second layout or entity
model in the browser.

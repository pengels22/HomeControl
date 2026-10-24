# Pass 6 — Browser visual editor

## Delivered

- Added the authenticated `/editor` HCM route and navigation entry.
- Added a bounded visual canvas, card palette, JSON editing surface, draft save,
  publish, optimistic revision handling, and revision revert controls.
- Added the dashboard revision-history API used by the editor.
- Kept the browser surface preview-only: no panel actions are executed, and the
  global microphone mute policy remains platform-controlled.
- Added focused static UI coverage for the route, safety language, card selector,
  and responsive editor styles.

## Validation

The editor uses the Pass 4 declarative compiler and therefore preserves the
1024x600 geometry, card allowlist, page/card limits, and `area.current` selector.
Browser and physical ESP32-P4 hardware validation remain separate gates; this
pass does not claim live panel commissioning or HIL validation.

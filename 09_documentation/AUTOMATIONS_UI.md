# Automation management UI

Settings → Automations combines native HCM Automations with the persisted Home
Assistant migration workspace. Rows are labeled `NATIVE`, `HA IMPORTED`, or
`HA STAGED`. Staged rows are review data only: they never register with the
scheduler, event watchers, or Automation Engine.

A staged row displays the original source alias, compatibility result, planned
enabled state, and the `HA_RUNTIME_STATE` provenance used for the current user
runtime snapshot. Its toggle changes only the planned import state. Native rows
use the existing enable/disable API and change live HCM runtime state.

The list supports friendly-name search, source filtering, enabled/disabled and
not-imported state filters, and compatibility filters. Duplicate aliases remain
separate rows; a short identity suffix distinguishes them. Search trims the
query for display and matching while the stored source alias remains unchanged.

Opening a staged row shows compatibility details, the visual trigger/condition/
action summaries, the sanitized Home Assistant source YAML, and the read-only
native preview. The source YAML is not HCM YAML and is never applied from this
page. Opening a native row shows the HCM definition in visual and YAML modes;
valid YAML is parsed and validated before persistence.

`Add Automation` opens a native HCM draft with an enabled, safe conversation
trigger and stop action. Saving validates the definition and registers the
native automation normally. The UI does not create helpers or import staged
Home Assistant records. Import remains a separately gated operation.

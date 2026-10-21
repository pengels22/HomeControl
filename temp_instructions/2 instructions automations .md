Repository:
pengels22/HomeControl

Branch:
main

Starting SHA:
<LATEST_BRIDGE_SHA>

==================================================
HCM AUTOMATIONS / SCRIPTS / HELPERS / HA MIGRATION
MASTER IMPLEMENTATION SPECIFICATION
==================================================

IMPORTANT

Read and follow AGENTS.md before changing anything.

This is a large subsystem. Implement it in coherent internal passes, but keep the
architecture unified.

DO NOT repeatedly run the full pytest suite.

During implementation:
- inspect only relevant code once identified
- use focused tests
- use focused DB tests
- use focused frontend syntax/tests
- do not repeatedly rescan the repository
- do not repeatedly run full CI-equivalent validation

At the end:
- run full pytest once
- if failures occur, fix with focused tests
- run full pytest one final time only
- compile once
- JS syntax once
- git diff --check once
- migration clone test once

Do not deploy automatically until all software validation and migration checks
are green.

==================================================
1 — PRIMARY GOAL
==================================================

Build HCM's first complete native automation subsystem.

HCM is intended to replace Home Assistant as the long-term local control and
automation platform.

The subsystem must include:

- Automation Engine
- visual Automation Editor
- YAML editor
- Home Assistant YAML compatibility/import
- Scripts
- Helpers
- compatibility Scenes support
- scheduler
- event bus integration
- expression/template engine
- run modes
- traces/history/debugging
- import mapping/review workflow
- entity namespace
- dynamic room/purpose targeting
- calendar trigger framework
- MQTT automation support
- Matter automation support
- webhooks
- API
- authentication/authorization
- persistence
- frontend pages

This is NOT merely a UI mockup.

The backend must actually execute supported automations.

==================================================
2 — NON-NEGOTIABLE SAFETY ARCHITECTURE
==================================================

Automations are a normal HCM command source only.

Required path:

Automation Engine
    ->
HCM command request
    ->
existing Safety / Arbitration / Binding / Commissioning gates
    ->
module

Automations MUST NOT bypass:

- life safety / fire arbitration
- maintenance lockout
- module commissioning
- normal output authorization
- RCM HVAC heating/cooling interlock
- communication-loss safety
- existing command authorization
- logical binding rules

Life safety must NOT depend on the Automation Engine.

A broken/stopped Automation Engine must not interfere with fire handling,
physical-input supervision, or mandatory safety shutdown.

Automation-originated actions must be identifiable in audit logs.

==================================================
3 — BASIC AUTOMATION MODEL
==================================================

Conceptual model:

WHEN
    one or more triggers

AND IF
    optional conditions

THEN DO
    one or more actions

Multiple triggers are OR by default.

Conditions support nested boolean groups.

Actions support structured flow control.

Normal users should not need YAML, but YAML is the canonical compatibility
format and must be available.

==================================================
4 — STORAGE MODEL
==================================================

PostgreSQL remains authoritative.

Add forward migrations only.

Do NOT rewrite existing applied migrations.

Store automations as individual durable records.

Each automation should include at least:

- stable database ID
- durable automation UUID if useful
- HA-compatible automation ID where imported
- entity_id
- alias/name
- description
- enabled
- mode
- max concurrency/queue
- YAML source
- normalized/compiled representation
- validation status
- compatibility/import status
- created_at
- updated_at
- last_triggered_at
- original_import_yaml if imported
- import source metadata if relevant

Do NOT use display names as durable identity.

Individual automation records must support full YAML import/export.

Also support bulk HA-style automations.yaml import/export.

==================================================
5 — ENTITY REGISTRY / ENTITY IDS
==================================================

Add or extend a real HCM entity namespace.

Examples:

light.kitchen_ceiling
switch.landscape_fountain
sensor.living_room_temperature
binary_sensor.front_door
climate.house
automation.sunset_lighting
script.bed_time
scene.seasonal
input_boolean.guest_mode
input_number.motion_timeout
input_text.message
input_select.house_mode
input_datetime.wakeup
input_button.volume_up
timer.kitchen
counter.garage_open_count
schedule.outdoor_lighting

Entity IDs are configuration-facing identifiers.

The authoritative immutable identity remains the underlying database ID.

Renaming a display name must not silently break automations.

Imported HA entity IDs should be preserved whenever possible.

Entity ID changes, when allowed, must be explicit and audited.

==================================================
6 — HOME ASSISTANT YAML COMPATIBILITY
==================================================

HCM must deliberately support Home Assistant automation YAML.

Support both older and newer HA syntax.

Examples that MUST normalize to the same internal model:

OLD:

trigger:
  - platform: time
    at: "18:00:00"

NEW:

triggers:
  - trigger: time
    at: "18:00:00"

Also support both:

service: light.turn_on

and:

action: light.turn_on

Similarly accept singular/plural:

trigger / triggers
condition / conditions
action / actions

Normalize these internally.

Do not require users to rewrite imported HA YAML merely because HA changed its
preferred key spelling.

==================================================
7 — USER'S EXISTING HA CONFIGURATION IS AN
ACCEPTANCE BASELINE
==================================================

The user's captured HA configuration includes approximately:

- 126 automations
- 8 scripts
- 4 scenes

The importer and parser must support the syntax constructs represented by that
configuration.

Known constructs include:

TRIGGERS:
- device
- state
- numeric_state
- time
- time_pattern
- sun
- zone
- conversation
- event
- manual/no trigger
- wait_for_trigger state triggers

CONDITIONS:
- device
- state
- numeric_state
- time
- template
- trigger ID
- AND
- OR
- nested conditions

FLOW/ACTIONS:
- normal service/action calls
- if / then / else
- choose
- delay
- wait_for_trigger
- repeat
- variables
- parallel action branches
- stop
- condition-as-action
- continue_on_timeout
- aliases on steps
- per-step enabled where present
- response_variable
- templates inside service data
- automation.trigger
- automation.turn_on
- automation.turn_off
- automation.toggle
- script calls
- scene.turn_on
- scene.create dynamic snapshots

Known service/domain usage includes examples from:

- light
- switch
- climate
- alarm_control_panel
- notify
- media_player
- tts
- automation
- script
- scene
- input_boolean
- input_number
- input_select
- timer
- vacuum
- weather
- shell_command
- HEOS/media integrations
- device_tracker/person
- MQTT-backed sensors

The parser must understand the automation structure even when an external
service adapter is not yet implemented.

==================================================
8 — TRIGGER SUPPORT
==================================================

V1 trigger types:

- state
- numeric_state
- device
- time
- time_pattern
- sunrise
- sunset
- sun with offset
- zone
- calendar
- event
- conversation
- MQTT
- webhook
- module online
- module offline
- HCM system event
- helper changes
- manual invocation

State triggers must support:

- from
- to
- for
- attribute where applicable
- trigger id
- multiple entities

Numeric state must support:

- above
- below
- attribute
- for
- templated numeric thresholds if safely supported

Time:

- exact time
- weekday
- helper/entity time source where HA syntax supports it

Time pattern:

- hour
- minute
- second patterns

Sun:

- sunrise
- sunset
- positive/negative offsets

Zone:

- enter
- leave

Calendar:

- event start
- event end
- offset before
- offset after
- calendar entity/provider
- optional title matching/filtering

MQTT:

- topic
- payload
- optional value extraction/template
- QoS metadata as appropriate
- retained-message semantics must be explicit

Webhook:

- stable generated webhook ID
- authenticated/private by default
- methods validated
- no automatic privileged device control

==================================================
9 — CONDITIONS
==================================================

Support:

- state
- numeric_state
- device
- time
- sun
- template
- HCM expression
- trigger ID
- AND
- OR
- NOT

Nested boolean trees must work.

Conditions must be usable:

- as top-level automation conditions
- inside choose
- inside if
- inside repeat while/until
- as condition steps inside action sequences

==================================================
10 — ACTION / FLOW LANGUAGE
==================================================

Support:

- service/action call
- delay
- wait_for_trigger
- wait_template
- if / then / else
- choose / default
- repeat
- parallel
- variables
- stop
- condition action
- script execution
- automation execution
- scene execution
- helper mutation
- MQTT publish
- Matter command
- HTTP/webhook action
- notification
- TTS
- HCM device control
- HCM room/purpose control

Repeat modes:

- count
- while
- until
- for_each

Wait operations:

- timeout
- continue_on_timeout

Network/external actions should support explicit timeout behavior.

Support continue_on_error where practical and HA-compatible.

==================================================
11 — TARGETING
==================================================

Support BOTH:

A. explicit targets

Example:

target:
  entity_id:
    - light.kitchen_ceiling
    - light.kitchen_sink

B. HCM dynamic selectors

Example:

target:
  room_id: 4
  purpose: LIGHTING

or equivalent validated HCM-native syntax.

Dynamic selectors are evaluated at execution time.

Therefore:

Room = Kitchen
Purpose = LIGHTING

can automatically include future Kitchen lights.

Bridge flags such as mqtt_enabled/matter_enabled must NOT affect native HCM
dynamic targeting.

==================================================
12 — RUN MODES
==================================================

Support HA-like modes:

single
restart
queued
parallel

Hard outstanding-work ceiling:
10

Semantics:

single:
- max active = 1
- trigger while active is rejected/logged

queued:
- max 10 total outstanding
- one active + up to nine queued
- 11th rejected/logged

parallel:
- max 10 active
- 11th rejected/logged

restart:
- new trigger cancels/replaces current execution
- protect against restart storms
- no more than 10 outstanding/replacement transitions in the active churn window
- further triggers rejected/logged until load falls back below ceiling

Imported HA max values may be accepted but HCM hard ceiling is 10.

If YAML requests max > 10:
- normalize/reject clearly
- never silently allow more than 10

==================================================
13 — RESTART / PERSISTENCE SEMANTICS
==================================================

IMPORTANT USER DECISION:

Delayed/waiting automation executions DO NOT survive HCM restart.

Examples:

delay
wait_for_trigger
wait_template
repeat currently waiting

are abandoned on restart.

Record trace state as:

ABORTED
reason: HCM_RESTART

Do not reconstruct partially completed action sequences after reboot.

==================================================
14 — SCHEDULE CATCH-UP
==================================================

Missed scheduled triggers MUST be caught up.

Catch-up window:
24 hours

After HCM starts:

- determine scheduled occurrences missed during downtime
- execute missed occurrences no older than 24h
- do not execute occurrences older than 24h
- maintain durable scheduler ledger
- prevent duplicate catch-up after another restart
- each missed occurrence should execute once

This applies to scheduler-based triggers such as:

- exact time
- schedule helper
- calendar start/end where appropriate
- sunrise/sunset where meaningful

Catch-up execution must be marked as catch-up in trace/history.

Do NOT catch up state-change triggers that occurred while HCM was offline unless
the integration provides a real event/history mechanism explicitly supporting
that behavior.

==================================================
15 — HELPERS
==================================================

Add a first-class Helpers section.

V1 HA-compatible helper types:

- input_boolean
- input_button
- input_number
- input_text
- input_select
- input_datetime
- counter
- timer
- schedule

Each helper needs:

- stable DB ID
- HA-compatible entity_id
- display name
- type/domain
- configuration
- current state
- attributes
- optional room association where appropriate
- created_at
- updated_at
- enabled if useful
- audit history for ADMIN changes

Helper actions should mimic common HA service names.

Examples:

input_boolean.turn_on
input_boolean.turn_off
input_boolean.toggle

input_number.set_value
input_number.increment
input_number.decrement

input_select.select_option
input_select.select_first
input_select.select_last
input_select.select_next
input_select.select_previous

input_text.set_value

input_datetime.set_datetime

counter.increment
counter.decrement
counter.reset
counter.set_value

timer.start
timer.pause
timer.cancel
timer.finish

schedule state must reflect configured active periods.

input_button should emit a state/event change suitable for triggering automations.

Helper state should persist where appropriate.

Timer-helper restoration is separate from automation delay restoration.

If timer restore support is implemented, make it explicit/configurable and do
not confuse timer helper restoration with resuming interrupted automation runs.

==================================================
16 — FUTURE HELPER TYPES
==================================================

Design helper schema so later HCM versions can add HA-style derived helpers
without another major redesign:

- Group
- Template
- Threshold
- Statistics
- Trend
- Min/Max
- Derivative
- Integral
- Utility Meter
- History Stats
- Times of Day
- Workday
- other calculated helpers

These do NOT all need full implementation in this pass unless simple to add.

Do not fake support.

==================================================
17 — SCRIPTS
==================================================

Scripts ship with this subsystem.

Scripts use the SAME action-sequence engine as Automations.

Add:

- Scripts page
- create/edit/delete/disable
- visual editor
- YAML editor
- HA scripts.yaml import/export
- stable script entity_id
- mode
- max <= 10
- variables/fields where compatible
- trace/history
- script-to-script calls
- automation-to-script calls

Existing HA scripts include examples such as:

- phone location update
- vacuum update/control
- HVAC off
- TV sleep timer
- warning notification
- TTS generation
- kitchen timer
- alarm critical notification

Unsupported external service calls should be marked as needing integration
mapping, not as a parser failure.

==================================================
18 — SCENES
==================================================

The user does NOT plan to make Scenes a major new HCM workflow.

However Scenes MUST exist for HA compatibility.

Support:

- scene.turn_on
- static imported scenes
- scenes.yaml import/export
- scene.create
- snapshot_entities
- dynamic runtime scene restoration

Dynamic runtime scenes may be non-durable across HCM restart unless explicitly
saved.

Do not build an elaborate Scene-centric architecture.

A simple compatibility Scenes page is sufficient:

- list
- enable/disable if applicable
- YAML
- state/entity members
- run/apply
- import/export

==================================================
19 — SINGLE EXPRESSION ENGINE
==================================================

Implement ONE HCM expression evaluator.

Do NOT build separate execution engines for Jinja and HCM expressions.

Architecture:

HA/Jinja-compatible syntax parser
               \
                -> normalized HCM expression AST
               -> typed sandboxed evaluator
                /
HCM native syntax parser

Both syntaxes compile into the SAME AST/evaluator.

==================================================
20 — EXPRESSION TYPES
==================================================

Support typed values:

- null / unknown
- boolean
- integer
- float
- string
- datetime
- date
- duration
- list/array
- map/object
- entity reference
- room reference

Support safe operators:

== !=
> >= < <=
+ - * / %
AND OR NOT
in
contains

and safe string/list/object operations where appropriate.

No arbitrary Python execution.

No eval().

==================================================
21 — HA / JINJA COMPATIBILITY
==================================================

Support the Jinja/template constructs actually represented in the user's HA
configuration, including common forms of:

{{ ... }}
{% if %}
{% elif %}
{% else %}
{% endif %}
{% set %}
list construction
map/object lookup
attribute lookup

Functions/helpers:

states(...)
is_state(...)
state_attr(...)
now()
as_datetime(...)
timedelta(...)

Common filters/operations:

float
int
round
join
replace
default
string formatting
date/time formatting
split
basic list operations
conditionals

The user's existing templates include examples using:

- lists
- append
- join
- nested if
- entity states
- entity attributes
- now()
- timedelta()
- as_datetime()
- date()
- strftime()
- split()
- replace()
- numeric conversion
- response-variable data

Implement a safe compatibility subset large enough to support those patterns.

Unsupported Jinja constructs must return explicit validation/import errors.

Do NOT silently evaluate unsupported constructs incorrectly.

==================================================
22 — HCM NATIVE EXPRESSIONS
==================================================

Also expose cleaner HCM-native syntax.

Examples:

sensor.living_room_lux < 50

input_boolean.guest_mode == false

sun.below_horizon == true

room("Kitchen").occupied == true

Recommended functions:

state("sensor.example")
attr("sensor.example", "unit")
is_on("light.kitchen")
available("sensor.example")
age("binary_sensor.motion")
room("Kitchen")
now()
coalesce(...)
min(...)
max(...)
round(...)
float(...)
int(...)

Native expressions and Jinja must resolve through the same entity/state provider.

==================================================
23 — EXPRESSION TESTER UI
==================================================

Add a developer/test surface accessible from Automations or Settings.

Support:

- HA/Jinja mode
- HCM Expression mode
- expression input
- validation
- result
- inferred type
- referenced entities
- errors
- execution context preview

Example:

{{ states('sensor.average_temp') | float < 60 }}

or:

sensor.average_temp < 60

No output/device commands should be executed by the expression tester.

==================================================
24 — EVENT BUS
==================================================

Create or formalize an HCM application event bus.

Normalized event sources include:

- HCM entity state changes
- physical/module state updates
- helpers
- MQTT devices
- Matter devices
- calendar
- scheduler
- webhook
- module connectivity
- system events

Automation triggers subscribe to normalized events.

Do NOT require automation code to know physical module/channel addresses.

==================================================
25 — MQTT AUTOMATION INTEGRATION
==================================================

Use the HCM-local MQTT infrastructure created by the bridge pass.

Support:

Trigger:
- raw MQTT topic trigger for compatibility/advanced use

Action:
- MQTT publish

Prefer normalized registered MQTT devices for normal state/device triggers.

Prevent MQTT feedback loops by preserving origin/correlation metadata where
possible.

Do not let arbitrary MQTT publishing bypass HCM command authority.

==================================================
26 — MATTER AUTOMATION INTEGRATION
==================================================

Support normalized Matter-backed entities when HCM Matter controller/import
support exists.

Actions against Matter devices must go through the Matter integration.

Matter-exposed HCM devices still go through normal HCM arbitration.

Raw Matter protocol details should not appear in ordinary automation YAML.

If inbound Matter controller support is not complete yet:
- provide clean adapter interface
- mark imported Matter-dependent actions as unavailable
- do not fake device availability

==================================================
27 — CALENDAR
==================================================

Create a calendar abstraction sufficient for automation triggers.

Support HCM calendar entities/providers.

V1 needs:

- event starts
- event ends
- offset before
- offset after
- title/summary matching where configured
- description/location attributes
- next-event state/attributes

Imported HA calendar entities should be mappable.

Calendar implementation must use configured HCM timezone.

Do not hardcode geographic location.

Sunrise/sunset calculations require HCM system location settings:
- latitude
- longitude
- timezone

If HCM location is not configured:
- sun triggers must report unavailable/configuration required
- do not guess

==================================================
28 — SERVICE/ACTION REGISTRY
==================================================

Create a central action/service registry.

Purpose:

HA YAML can reference:

light.turn_on
switch.turn_off
climate.set_temperature
script.foo
automation.trigger
etc.

The parser should validate structure separately from service availability.

Statuses:

SUPPORTED
TRANSLATED
NEEDS_MAPPING
UNAVAILABLE
UNSUPPORTED_SYNTAX

Do not treat an unavailable integration as invalid YAML.

==================================================
29 — REQUIRED CORE ACTION DOMAINS
==================================================

Native HCM support should include at least:

light:
- turn_on
- turn_off
- toggle
- brightness/brightness_pct
- transition if supported by target

switch:
- turn_on
- turn_off
- toggle

climate:
- turn_on
- turn_off
- set_hvac_mode
- set_temperature

automation:
- trigger
- turn_on
- turn_off
- toggle

script:
- execute/call

scene:
- turn_on
- create snapshot

helpers:
- normal HA-compatible helper actions

timer:
- start
- pause
- cancel
- finish

counter:
- increment
- decrement
- reset/set

MQTT:
- publish

webhook/HTTP:
- outbound request through controlled integration

HCM:
- room/purpose action
- device control
- system variable/helper operations

All physical HCM actions must still go through normal control gates.

==================================================
30 — EXTERNAL SERVICE ADAPTERS
==================================================

The user's HA configuration references external services such as:

- mobile notifications
- TTS
- media_player
- HEOS
- weather.get_forecasts
- vacuum
- alarm control
- shell commands
- SmartThings-backed entities
- Nest-backed climate
- calendars

Implement a generic adapter boundary.

If a service is not yet available:
- parser still accepts it
- importer flags it
- automation remains disabled if execution would be unsafe/incomplete
- UI explains exactly which service requires mapping/integration

Do not pretend unsupported integrations work.

==================================================
31 — RESPONSE VARIABLES
==================================================

Support service/action calls that return structured data.

HA compatibility example:

- action: weather.get_forecasts
  response_variable: daily_forecast

Then later actions/templates may reference:

daily_forecast

Variables must support structured list/map data.

Trace UI should show safe response-variable metadata/value where appropriate.

Do not leak credentials/secrets into traces.

==================================================
32 — VARIABLES
==================================================

Support:

automation-level variables
action-level variables
script parameters/variables
response_variable
repeat variables
trigger object
wait object/context
local branch scope where appropriate

Imported HA templates should resolve familiar variables such as:

trigger
repeat
wait
this
response variables

Implement only semantics that can be accurately supported.

==================================================
33 — AUTOMATION CONTROL ACTIONS
==================================================

Support:

automation.turn_on
automation.turn_off
automation.toggle
automation.trigger

Compatibility options:

skip_condition
stop_actions

Turning an automation off with stop_actions should cancel its current run(s).

Cancellation must appear clearly in traces.

==================================================
34 — TRACE / HISTORY SYSTEM
==================================================

This is required, not optional.

For each run record:

- run ID
- automation ID
- trigger timestamp
- trigger source
- trigger ID
- catch-up flag
- mode
- start time
- finish time
- duration
- final result
- error if any
- cancellation reason
- restart-aborted state if applicable

Per-step trace should record:

- step path/index
- alias
- type
- inputs
- condition result
- resolved targets
- evaluated template/expression result
- action result
- inhibition/safety rejection
- duration
- errors

Example UI:

Trigger
  Front Door -> Open
  PASS

Condition
  After 16:30
  PASS

Condition
  Guest Mode == Off
  PASS

Action
  Kitchen Lighting -> ON
  ACCEPTED

Command arbitration
  ACCEPTED

Run result
  SUCCESS

Never log secrets or passwords in trace payloads.

==================================================
35 — DRY RUN / TEST MODE
==================================================

Add a Test/Dry Run feature.

Dry Run may:

- parse YAML
- evaluate expressions
- evaluate conditions
- resolve entities
- resolve room/purpose selectors
- show target actions
- simulate branching

Dry Run MUST NOT:

- command physical outputs
- publish MQTT unless explicitly using a mock/test channel
- command Matter devices
- send real notifications
- run shell commands
- change helper state unless using isolated preview state

Example result:

WOULD TURN ON:
- Kitchen Ceiling
- Sink Light
- Under-Cabinet Lighting

No physical outputs commanded.

==================================================
36 — IMPORTER
==================================================

Add "Import Home Assistant" workflow.

Accept:

- automations.yaml
- scripts.yaml
- scenes.yaml

Import must be analysis-first.

Do not immediately enable imported content.

For each item classify:

COMPATIBLE
TRANSLATED
NEEDS_MAPPING
UNAVAILABLE_SERVICE
UNSUPPORTED

Preserve original YAML.

Show unresolved entities/services.

Imported automations with unresolved mappings remain disabled.

==================================================
37 — IMPORT ENTITY MAPPING
==================================================

Attempt automatic mapping using:

- exact entity_id
- stable imported IDs if available
- display name
- room
- semantic type/domain
- known HCM logical bindings

Do not guess ambiguous mappings.

UI example:

light.living_room_lamp
  -> Living Room Lamp
     confidence: exact entity ID
     [Mapped]

sensor.rmc_prototype_illuminance
  -> Living Room Illuminance
     [Confirm]

notify.mobile_app_iphone_16
  -> no HCM provider
     [Needs Mapping]

Mappings should be persisted so later imports can reuse them.

==================================================
38 — IMPORT REPORT
==================================================

Display summary such as:

126 automations discovered

98 Compatible
18 Translated
8 Needs Mapping
2 Unsupported

8 scripts discovered
4 scenes discovered

Provide:

[Review Mappings]
[Import Compatible Disabled]
[Export Report]

Do not silently drop unsupported triggers/actions.

==================================================
39 — VISUAL AUTOMATION EDITOR
==================================================

The normal UI should intentionally feel familiar to Home Assistant.

Layout:

Automation Name
Description
Enabled
Mode

WHEN
  Trigger card
  Trigger card
  + Add Trigger

AND IF
  Condition card
  AND/OR group
  + Add Condition

THEN DO
  Action card
  Delay
  Choose
  If
  Repeat
  Parallel
  Wait
  + Add Action

Top-level controls:

Save
Run / Test
Dry Run
Trace
Edit in YAML
Duplicate
Delete

READONLY users may inspect.

ADMIN users may edit.

==================================================
40 — YAML EDITOR
==================================================

Every Automation and Script needs:

Visual Editor
YAML Editor

Switching between them must operate on the same normalized model.

YAML editor requirements:

- syntax highlighting
- indentation support
- validation
- line/column errors
- compatibility warnings
- entity/service autocomplete if practical
- no save when structurally invalid
- warning before visual-editor conversion loses unsupported formatting/comments

Preserve original imported YAML separately even if normalized YAML is regenerated.

==================================================
41 — VISUAL EDITOR CARD TYPES
==================================================

Trigger cards should expose relevant fields dynamically.

Examples:

State:
- Entity
- From
- To
- For

Numeric:
- Entity
- Attribute
- Above
- Below
- For

Time:
- Time
- Weekdays

Sun:
- Sunrise/Sunset
- Offset

MQTT:
- Topic
- Payload/template

Calendar:
- Calendar
- Start/end
- Offset
- Match

Webhook:
- generated ID
- allowed methods

Condition cards similarly adapt to type.

Action cards adapt to service/domain.

==================================================
42 — VISUAL TARGET PICKER
==================================================

Support target selection by:

- Entity
- Device
- Room
- Purpose
- dynamic HCM room+purpose selector

Show whether target is:

STATIC

or

DYNAMIC

Example:

Kitchen + LIGHTING
Dynamic: includes future matching devices

This distinction should be obvious.

==================================================
43 — FRONTEND NAVIGATION
==================================================

Add an Automation area with tabs/subpages:

Automations
Scripts
Helpers
Scenes
Traces / History
Import
Expression Tester

Scenes may be visually deemphasized because they are primarily compatibility
support.

==================================================
44 — AUTOMATIONS LIST PAGE
==================================================

List should show:

- enabled toggle
- alias/name
- entity_id
- trigger summary
- last triggered
- last result
- mode
- current running count
- warning/error badge
- import/mapping status

Filters:

- enabled/disabled
- room if relevant
- trigger type
- status
- imported/native
- compatibility warning

Search by alias/entity ID.

==================================================
45 — SCRIPTS PAGE
==================================================

Similar to Automation editor but without trigger section.

Show:

Name
Description
Mode
Fields/variables
Sequence
YAML
Trace
Run
Dry Run

==================================================
46 — HELPERS PAGE
==================================================

HA-like helper management.

Add Helper flow:

Choose type:

Toggle
Button
Number
Text
Dropdown
Date/Time
Counter
Timer
Schedule

Then type-specific configuration.

Examples:

Number:
- min
- max
- step
- unit
- initial/restore policy

Dropdown:
- options
- initial

Text:
- max length
- pattern if supported

Date/Time:
- date
- time
- both

Counter:
- min/max/step/initial

Timer:
- duration
- optional restore policy

Schedule:
- weekday/time blocks

==================================================
47 — SCENES PAGE
==================================================

Compatibility-first.

Support:

- imported scenes
- scene entity ID
- state assignments
- YAML
- apply
- duplicate
- delete

Dynamic runtime snapshots should appear separately or be marked temporary.

==================================================
48 — TRACE UI
==================================================

Provide a run timeline.

Expandable steps:

Trigger
Conditions
Actions
Branches
Templates
Waits
Service calls
Arbitration result
Errors

Allow selecting historical run.

Keep reasonable retention configurable.

==================================================
49 — API
==================================================

Authenticated REST API at minimum for:

Automations:
GET list/detail
POST create
PUT/PATCH update
DELETE
POST enable/disable
POST trigger
POST dry-run
GET traces/history
GET YAML
PUT YAML

Scripts:
GET/POST/PATCH/DELETE
POST run
POST dry-run

Helpers:
GET/POST/PATCH/DELETE
POST action

Scenes:
GET/POST/PATCH/DELETE
POST apply

Imports:
POST analyze
POST mapping
POST commit
GET report

Expressions:
POST validate/evaluate

Entity registry:
GET search/resolve

Automation metadata/service registry:
GET available triggers
GET available conditions
GET available actions/services

READONLY:
- inspect only

ADMIN:
- mutate/run where allowed

==================================================
50 — WEBSOCKETS / LIVE UI
==================================================

Use a live update mechanism if consistent with existing HCM architecture.

Frontend should update:

- automation running state
- helper state
- trace progress
- entity state
- import progress

Avoid wasteful tight polling if a clean event stream already exists or can be
added simply.

==================================================
51 — AUDIT
==================================================

Audit:

- automation created
- modified
- enabled/disabled
- deleted
- manually triggered
- import committed
- mapping changed
- helper created/changed/deleted
- script changed
- scene changed

Do not audit every normal high-frequency state event into the administrative
audit table unless appropriate.

Operational traces are separate from admin audit.

==================================================
52 — AUTHORIZATION
==================================================

ADMIN:
- create/edit/delete
- enable/disable
- trigger/run
- configure helpers
- import
- edit mappings

READONLY:
- inspect definitions
- inspect traces/status
- inspect helpers
- cannot cause automation execution
- cannot mutate helper state

Touch/KIOSK permissions must follow existing token/scope architecture rather than
implicitly granting ADMIN.

==================================================
53 — SHELL COMMAND SECURITY
==================================================

The user's HA configuration includes shell_command actions.

Do NOT allow arbitrary YAML to execute arbitrary shell strings.

If shell-command compatibility is added:

- commands must be pre-registered by ADMIN
- YAML references a registered command ID/name
- command path/arguments are validated
- no arbitrary shell interpolation from untrusted state/template data
- credentials remain protected
- execution timeout required
- audit execution

Imported unknown shell_command actions:
NEEDS_MAPPING / UNAVAILABLE

==================================================
54 — WEBHOOK / HTTP SECURITY
==================================================

Outbound HTTP actions:

- configurable timeout
- restricted credential handling
- secrets referenced by secret ID, not embedded in trace
- no automatic local-admin bypass

Inbound webhooks:

- stable random ID/token
- optional authentication
- method restrictions
- rate limiting
- event payload size limits
- cannot directly bypass automation/action authorization

==================================================
55 — CONVERSATION TRIGGERS
==================================================

The user's HA automation YAML includes conversation triggers.

Add parser/model support.

If HCM voice/conversation service is not yet implemented:

- imported conversation triggers parse successfully
- status = UNAVAILABLE_SERVICE
- automation remains disabled until mapped/provider exists

Do not mark the YAML unsupported.

Design interface so the future companion app or voice layer can emit normalized
conversation-intent events.

==================================================
56 — NOTIFICATION ADAPTER
==================================================

Automation action model should support:

notify.<target>

HCM's future companion app will become the preferred notification endpoint.

For now:

- create clean notification service registry
- map any existing native notification path
- imported mobile_app targets may be marked Needs Mapping
- do not depend on Home Assistant

Life-safety notification path remains independent as already designed.

==================================================
57 — TTS / MEDIA
==================================================

Automation action model must support future/native:

tts
media_player

Existing HA migration includes TTS and media volume operations.

Implement parser/action registry support.

Use existing HCM media/TTS capability if present and valid.

Do not require Home Assistant.

Unsupported HA cloud-specific TTS provider should be shown as provider mapping
required rather than invalid automation syntax.

==================================================
58 — WEATHER RESPONSE ACTION
==================================================

Because the user's existing automations use:

weather.get_forecasts
response_variable

the action system must support structured service response variables even if
weather provider integration is initially unavailable.

Importer should flag provider mapping, not parser failure.

==================================================
59 — AUTOMATION DEPENDENCY GRAPH
==================================================

Build dependency inspection.

Track references to:

- automations
- scripts
- scenes
- helpers
- entities
- services

Before deletion:

show references.

Example:

Cannot safely delete input_boolean.guest_mode.

Referenced by:
- Sunset Lighting
- Bed Time
- Vacation Reset

Allow ADMIN force-delete only with clear warning if existing project policy
permits it.

==================================================
60 — VALIDATION
==================================================

Validate on save:

- YAML syntax
- schema
- entity references
- helper references
- service availability
- trigger configuration
- expression syntax
- concurrency limits
- unsafe recursion
- obvious automation recursion loops where detectable

Recursive script/automation calls must have depth protection.

Set a maximum nested automation/script call depth.

Recommended initial limit:
20

Reject deeper recursion cleanly.

==================================================
61 — EVENT LOOP / LOOP PROTECTION
==================================================

Add event origin/correlation IDs.

Avoid common loops such as:

MQTT command
 -> HCM state
 -> MQTT publish
 -> inbound MQTT trigger
 -> same command

or:

automation A -> automation B -> automation A

Use:

- correlation ID
- origin
- call depth
- recursion protection
- existing state-change semantics

Do not suppress legitimate repeated state events globally.

==================================================
62 — SCHEDULER / TIMEZONE
==================================================

Use HCM configured timezone.

DST must be handled correctly.

Do not assume UTC for user-facing schedules.

Scheduler ledger needs:

- automation ID
- trigger ID
- scheduled occurrence
- execution status
- catch-up status

Clock/time changes should not create duplicate occurrences.

==================================================
63 — UI STYLE
==================================================

The visual editor should intentionally resemble the usability of Home Assistant
without copying proprietary assets.

Use HCM's existing styling/navigation.

Goals:

- familiar card structure
- low-code
- expandable advanced fields
- clean YAML switch
- clear validation
- clear status
- no physical-address exposure for normal configuration

==================================================
64 — MIGRATION / DATABASE SAFETY
==================================================

Any new tables must use forward migrations.

Likely tables may include:

automation_definitions
automation_runs
automation_trace_steps
automation_schedule_ledger
scripts
scenes
helpers
entity_registry / aliases if needed
import_jobs
import_mappings
service_registry/config if needed

Names may differ if existing schema provides reusable structures.

Do not duplicate existing rules/scenes tables blindly.

Audit current schema first and migrate/reuse safely.

Preserve:

- users
- auth
- rooms
- channel metadata
- bindings
- bridge settings
- Matter endpoints
- module commissioning
- safety configuration

==================================================
65 — LEGACY RULES ENGINE
==================================================

Current repository documentation says the existing generalized Rules Engine is
planned/partial.

Audit it before implementation.

If useful components can be reused safely:
reuse them.

Do NOT preserve a weak/duplicated execution model just for compatibility.

There should be one authoritative Automation Engine after migration.

Old unused scaffolding may remain temporarily only if removal is risky.

Document what was superseded.

==================================================
66 — TEST FIXTURES FROM REAL HA YAML
==================================================

Create SANITIZED regression fixtures representative of the user's actual
automations.

Do not commit private alarm codes, credentials, tokens, addresses, secrets, or
private personal data.

Fixtures should cover at least:

- old trigger/platform syntax
- new trigger syntax
- device trigger
- state trigger
- numeric_state
- time
- time_pattern
- sun
- zone
- conversation
- event
- device conditions
- nested AND/OR
- trigger ID condition
- template
- variables
- response_variable
- choose
- if
- delay
- wait_for_trigger
- repeat/until
- parallel
- stop
- automation.trigger
- automation enable/disable
- script call
- static scene
- scene.create snapshot
- helper calls
- climate calls
- notification provider unavailable
- TTS provider unavailable
- shell-command mapping required

==================================================
67 — REQUIRED TEST AREAS
==================================================

Focused tests for:

Database:
- migrations
- stable IDs
- YAML persistence
- helper persistence
- mapping persistence
- schedule ledger

Parser:
- old/new HA syntax
- round-trip normalization
- invalid YAML
- unsupported syntax

Expression engine:
- Jinja compatibility
- HCM-native syntax
- same AST/evaluation result
- types
- datetime/duration
- list/map
- sandbox escape rejection

Engine:
- triggers
- conditions
- choose
- if
- repeats
- waits
- variables
- response variables
- cancellation
- recursion limits
- run modes
- 10-run ceiling

Restart:
- waits aborted
- traces marked HCM_RESTART
- scheduled catch-up <=24h
- no catch-up >24h
- duplicate catch-up prevented

Safety:
- automation cannot bypass arbitration
- maintenance rejection visible
- uncommissioned output remains blocked
- HVAC conflict blocked
- fire arbitration remains authoritative

Importer:
- compatible
- translated
- mapping
- unavailable service
- unsupported
- disabled unresolved imports

Frontend:
- list/editor rendering
- readonly disable
- YAML validation
- helper forms
- mapping UI
- trace rendering

==================================================
68 — PERFORMANCE
==================================================

Do not use a busy polling automation loop.

Use event-driven state triggers.

Scheduler should sleep efficiently until required occurrence.

Expression evaluation should be bounded.

Template execution needs:
- time limits
- recursion limits
- collection-size limits where necessary

One bad automation must not stall the entire engine.

==================================================
69 — FAILURE ISOLATION
==================================================

A failing automation:

- logs error
- ends/fails that run
- does not crash Automation Engine
- does not crash HCM
- does not interrupt Heartbeat
- does not interrupt safety handling
- does not corrupt scheduler

==================================================
70 — BACKUP / EXPORT
==================================================

Automation subsystem data must be covered by normal PostgreSQL backup.

Also support user export of:

automations.yaml
scripts.yaml
scenes.yaml

and preferably HCM helper export.

Export should avoid embedding secrets.

==================================================
71 — DOCUMENTATION
==================================================

Add authoritative white paper:

AUTOMATIONS_SCRIPTS_HELPERS.md

Document:

- architecture
- entity model
- YAML compatibility
- visual editor
- expression engine
- scheduler
- restart behavior
- catch-up
- run modes
- helper types
- script semantics
- scene compatibility
- imports
- traces
- safety path
- supported HA syntax
- unavailable integration behavior
- limits

Update IMPLEMENTATION_STATUS.md truthfully.

==================================================
72 — DO NOT CLAIM
==================================================

Do NOT claim:

- 100% Home Assistant compatibility
- unsupported integrations work
- arbitrary HA custom integrations work
- Matter devices work if not commissioned/imported
- mobile notifications work if no provider exists
- conversation works if no provider exists
- shell commands migrated if not mapped
- full migration success merely because YAML parses

Be explicit.

==================================================
73 — FRONTEND ACCEPTANCE
==================================================

At minimum, a logged-in ADMIN should be able to:

1. open Automations
2. create automation
3. choose trigger visually
4. add condition
5. add action
6. select explicit entity
7. select dynamic room/purpose target
8. save
9. switch to YAML
10. edit YAML
11. return to visual editor
12. dry-run
13. manually trigger
14. inspect trace
15. disable
16. duplicate
17. delete

Scripts:
- create/edit/run/trace

Helpers:
- create all v1 helper types
- change helper state

Scenes:
- inspect/import/apply

Import:
- upload HA YAML
- analyze
- review mappings
- import disabled
- enable after resolved

==================================================
74 — LIVE DEPLOYMENT GATE
==================================================

After implementation:

1. focused tests green
2. migration clone-test green
3. full pytest
4. compile
5. JS syntax
6. diff check
7. Docker/image build if affected
8. hosted CI exact SHA

Only then consider live HCM deployment.

Before deployment:

- DB backup
- restore clone
- apply new migrations to clone
- verify auth/users preserved
- verify rooms preserved
- verify channel metadata preserved
- verify bindings preserved
- verify bridge configuration preserved
- verify Matter endpoint allocation preserved

==================================================
75 — LIVE DEPLOYMENT RESTRICTIONS
==================================================

Deployment is non-actuating.

Do NOT:

- turn on physical lights
- command HVAC
- command relays
- run HIL
- alter commissioning
- alter fire input configuration
- change life-safety wiring state

Allowed software verification:

- create disabled test automation
- expression evaluation
- dry-run
- helper CRUD
- parser/import analysis
- schedule preview
- trace generation from non-actuating test actions

==================================================
76 — TEST EXECUTION POLICY
==================================================

Follow AGENTS.md strictly.

During coding:
focused tests only.

When feature is complete:

Run full pytest ONCE.

Then:

python -m compileall -q \
  00_Heartbeat \
  01_HCM \
  02_SIM \
  03_LCM \
  04_RCM \
  05_PNL \
  07_config \
  08_servises \
  11_scripts \
  12_tests \
  13_hardware_tests

Run:

git diff --check

Run JavaScript syntax checks once.

If pytest fails:
- fix with focused tests
- rerun full pytest one final time only

Do not repeatedly run the full suite during active development.

==================================================
77 — IMPLEMENTATION PASSES
==================================================

Work internally in this order:

PASS A
- schema/entity model
- parser/normalized automation model
- HA compatibility parser
- expression engine foundation

PASS B
- helpers
- scripts
- scenes compatibility
- action/service registry

PASS C
- event bus
- scheduler
- triggers
- conditions
- execution engine
- run modes
- catch-up/restart semantics

PASS D
- traces/history
- dry-run
- importer/mapping

PASS E
- frontend:
  Automations
  Scripts
  Helpers
  Scenes
  Import
  Traces
  Expression Tester

PASS F
- integration adapters:
  MQTT
  Matter
  calendar
  existing HCM commands

PASS G
- compatibility audit against sanitized HA fixtures
- documentation
- final validation

Do not run the complete suite after each pass.

==================================================
78 — FINAL REPORT
==================================================

Return a detailed final report containing:

1. starting SHA
2. ending SHA
3. migrations added
4. database objects added
5. entity registry design
6. automation storage format
7. normalized AST design
8. supported HA trigger syntax
9. supported conditions
10. supported action flow
11. supported services/domains
12. unavailable service behavior
13. Jinja compatibility scope
14. HCM expression syntax
15. expression security model
16. helper types implemented
17. scripts status
18. scenes status
19. dynamic scene snapshot status
20. run mode implementation
21. 10-run limit behavior
22. restart-abort behavior
23. 24-hour catch-up behavior
24. schedule ledger behavior
25. event bus behavior
26. MQTT trigger/action status
27. Matter automation status
28. calendar status
29. importer status
30. mapping UI status
31. visual editor status
32. YAML editor status
33. dry-run status
34. trace/history status
35. frontend screenshots/descriptions if available
36. focused test results
37. full pytest result
38. compile result
39. JS syntax result
40. diff check
41. migration clone-test result
42. hosted CI exact SHA/result
43. live deployment result if performed
44. /health result
45. /api/v1/version
46. login/auth result
47. PostgreSQL state
48. Heartbeat state
49. git status
50. remaining unsupported HA constructs/integrations

Final classification:

AUTOMATION_PLATFORM_V1_READY

or

AUTOMATION_PLATFORM_V1_PARTIAL
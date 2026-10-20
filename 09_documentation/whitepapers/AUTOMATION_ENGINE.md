# Automation Engine V1

The Automation Engine is a provider-neutral execution layer over HCM's
integration contracts. Automations store immutable entity database references,
semantic service names, JSON trigger/condition/action definitions, and a
revision. Providers are never referenced by Python handler identity.

## Durable execution

Migration `017_automation_engine.sql` adds `automations`, `automation_runs`,
`automation_engine_state`, and `automation_schedule_ledger`. The engine owns a
cursor over `integration_events`; it reads events in ascending order, evaluates
all enabled automations, and advances the cursor only after evaluation. An
in-process wake-up may reduce latency, but the durable cursor is the recovery
source. A failed run does not block other automations or permanently replay an
event.

On startup, previously running runs become `HCM_RESTART`. Pending `for`
timers and delay actions are in memory and are cancelled on restart. V1 does
not resume a partially completed action sequence.

## Definitions and execution

Definitions are `WHEN` trigger lists, optional boolean conditions, and
sequential actions. Implemented triggers are state, durable event, wall-clock
time model validation, time-pattern model validation, and an explicit sun
contract. Sun execution remains unavailable until a native HCM Sun subsystem is
provided. Conditions are state, numeric state, local time (including overnight
windows), AND, OR, and NOT. Actions are service calls through the Service
Registry, bounded cancellable delays, condition-as-action, and stop.

Modes are `single`, `restart`, `queued`, and `parallel`; queue/concurrency is
bounded to ten. Native actions also include `if`, first-match `choose`, bounded
`repeat`, bounded `parallel`, wait-until conditions, and `wait_for_trigger`.
Action nesting is capped at ten levels, repeats at 100 iterations (or 100
`for_each` values), and parallel containers at ten branches. Parallel branches
receive copied variable scopes and branch mutations do not merge automatically.
Service calls retain target ownership and provider/instance resolution and
therefore continue through normal HCM authorization and safety paths. Dry-run
resolves and traces actions without invoking services.

Waits are in-memory and cancellable. `wait` reevaluates at a bounded interval;
`wait_for_trigger` uses the existing event path for state, numeric-state, and
event triggers. A matched result is exposed as `variables.wait` with `trigger`,
`event`, and `timed_out`. Timeouts set `timed_out`; `continue_on_timeout=false`
stops the run. Waits, repeat progress, and pending numeric `for` timers do not
resume after HCM restart. Numeric-state triggers fire only on non-matching to
matching crossings; `above` and `below` use strict boundaries.

Native `automation.turn_on`, `automation.turn_off`, and `automation.trigger`
services use the Service Registry and identify service-triggered runs with
`trigger_source=automation_service`. Their durable target is the automation
UUID (or an Automation entity whose immutable `automation_id` attribute is
resolved by the registry); display names are never used for dispatch. A
disabled target returns `disabled_target` without creating a run. `trigger`
can skip top-level conditions only when its explicit `evaluate_conditions`
argument is false.

Automation and script calls carry an internal invocation chain. A repeated
`automation:<uuid>` or `script:<uuid>` identity, or a chain at the depth limit,
is rejected before a run is created. This protects direct self-calls and
cross-automation/script cycles while preserving independent manual runs.
Cancellation sets the run event, cancels event waiters and pending timers, and
cleans waiter registrations even when a wait is interrupted.

Traces are bounded JSON data on each run. They include trigger source, action
steps, targets, sanitized arguments, results, and error classification. Secrets
are removed by key pattern. Public error categories include validation, missing
entity, unavailable target, service unavailable/failure, timeout, cancelled,
and internal error.

## API and authorization

`/api/v1/automations` provides authenticated list/create/get/update,
enable/disable/delete, run listing/trace inspection, and ADMIN-only manual run.
READONLY users may inspect definitions and runs. Manual runs identify
`trigger_source=manual` and do not fabricate provider event data.

Schedule ledger and 24-hour schedule catch-up are reserved for the scheduler
follow-up; this V1 core provides the durable schema and trigger contracts but
has not invented a sun calculation or replayed non-schedule integration events.
Expression evaluation, Home Assistant import, scripts/scenes/helpers, and the
visual editor are future phases.

## Scheduler completion

Schedule triggers receive a deterministic `trigger_id` derived from their
normalized definition. Migration 018 extends the occurrence ledger with that
identity, actual fire time, catch-up flag, and reason, and adds scheduler
checkpoint state. At startup HCM closes interrupted runs, checkpoints the
scheduler, reconstructs enabled schedules, executes at most the most recent
missed occurrence per trigger when it is no older than 24 hours, and records
older occurrences as skipped. Repeating patterns never replay every missed
interval. Disabled or edited automations cancel owned timers and future
scheduling; manual runs do not touch the ledger.

Exact local times and patterns are evaluated in the configured HCM timezone.
Nonexistent spring-forward wall times are skipped and repeated fall-back times
execute once using the first occurrence. Native sunrise/sunset calculation uses
configured latitude/longitude and timezone without network access; offsets are
stored as normalized seconds. A missing or impossible solar event is treated as
unavailable and does not stop the engine. Pending state `for:` timers remain
non-durable and are discarded on restart.

## Native zone triggers

The native zone subsystem consumes ordinary location-bearing tracker entity
updates. A zone trigger stores immutable `tracker_ref` and `zone_ref` values and
an `event` of `enter` or `leave`; the automation engine receives durable
`hcm_native.zone.enter` and `hcm_native.zone.leave` events through the existing
integration event cursor. Zone conditions read the same membership state.

Membership is tracked in memory per tracker and zone. The first available
location establishes membership without fabricating a crossing, and restart
reconstruction therefore emits no catch-up event. Unavailable trackers do not
imply a leave. V1 uses metres, the haversine distance, reported accuracy
conservatively, and a fixed five-metre leave hysteresis to reduce boundary
jitter. Coordinates are configuration and provider state; normal automation
trace context contains references and transition metadata, not coordinates.

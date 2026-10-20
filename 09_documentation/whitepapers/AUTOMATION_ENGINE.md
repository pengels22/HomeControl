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
bounded to ten. Service calls retain target ownership and provider/instance
resolution and therefore continue through normal HCM authorization and safety
paths. Dry-run resolves and traces actions without invoking services.

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

# Pass 7 legacy retirement assessment

SIM and RMC remain present as deprecated compatibility roles. Pass 2's additive
`module_type_deprecations` migration preserves historical records and blocks no
existing runtime path. The new PNL simulator has no SIM/RMC dependency: local
sensors, dashboard rendering, telemetry, commands, and Sonic sessions are all
panel-scoped.

Remaining references are retained for existing RCM channel management, legacy
configuration import, firmware compatibility tests, and safe rollback. Final
removal requires a production inventory proving that no deployed module or
automation consumes those roles, a migration of remaining sensor bindings to
PNL-backed entities, and an approved rollback window. No commissioning disable
or live service change was performed in this pass.

# HomeControl White Papers

This directory is the authoritative white-paper set for the HomeControl project beginning with the audited 2026-10-18/19 software baseline.

## Status

Merged into `main` by the documentation consolidation commit `82818c0`.
These papers are the retained documentation authority for the current synchronized
baseline; they do not authorize deployment or physical commissioning.

Code baseline used for the current documentation synchronization:

- Repository: `pengels22/HomeControl`
- Commit: `544c5c87594d955a2a33e2bac336ae5a536f2463`
- Hosted ACM CI: SUCCESS on the synchronized baseline
- ACM audit: [ACM V1 reconciliation](../../06_ACM/ACM_V1_RECONCILIATION.md) — `ACM_V1_READY_FOR_HIL`

These papers distinguish among:

- implemented and software-tested behavior;
- implemented but physically unverified behavior;
- simulated/mock-only behavior;
- planned behavior;
- superseded design decisions.

## White papers

- [Integration framework foundation](INTEGRATION_FOUNDATION.md)
- [Integration configuration and authentication](INTEGRATION_CONFIGURATION.md)
- [First real integration providers](FIRST_REAL_PROVIDERS.md)
- [Google Calendar and Gmail providers](GOOGLE_INTEGRATIONS.md)
- [Integration status and reconciliation](INTEGRATION_STATUS.md)
- [Automation Engine V1](AUTOMATION_ENGINE.md)
- [Automation Expressions and Templates](AUTOMATION_EXPRESSIONS.md)
- [Native Helpers, Scripts, and Scenes](NATIVE_PRIMITIVES.md)
- [Home Assistant Compatibility Analyzer and Importer](HA_IMPORTER.md)
- [Channel metadata, rooms, HVAC semantics and bridges](CHANNEL_METADATA_AND_BRIDGES.md)

- [System Architecture](HOMECONTROL_SYSTEM_WHITE_PAPER.md)
- [Implementation Status](IMPLEMENTATION_STATUS.md)
- [Life-Safety and Safety Arbitration](LIFE_SAFETY_AND_ARBITRATION.md)
- [Network, Communications, and Supervision](NETWORK_AND_HEARTBEAT.md)
- [Hardware Modules and I/O](HARDWARE_MODULES_AND_IO.md)
- [Security, Authentication, and Updates](SECURITY_AUTH_AND_UPDATES.md)
- [Commissioning and Validation Manual](COMMISSIONING_AND_VALIDATION.md)
- [Glossary and Acronyms](GLOSSARY.md)

The ACM V1 software baseline is ready for hardware-in-the-loop validation. This
does not commission ACM or any other HomeControl module.

## Documentation policy

The white papers describe what the current repository and approved architecture actually support. Historical documents under `10_documentation/` remain useful design records, but where they conflict with these white papers or the current audited source, they are historical rather than authoritative.

No hardware is considered physically commissioned solely because software tests pass. Physical commissioning status is tracked separately from software completeness.

## Current documentation-freeze baseline

The software baseline is considered ready for documentation freeze and ACM HIL
validation. This does not mean ACM or the installed physical system is commissioned.

Known physical gaps remain documented in the implementation-status and commissioning papers.

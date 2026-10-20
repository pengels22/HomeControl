# HomeControl White Papers

This directory is the authoritative white-paper set for the HomeControl project beginning with the audited 2026-10-18/19 software baseline.

## Status

Merged into `main` by the documentation consolidation commit `82818c0`.
These papers are the retained documentation authority for the current review
baseline; they do not authorize deployment or physical commissioning.

Code baseline used for the current draft:

- Repository: `pengels22/HomeControl`
- Commit: `6fc4179c3a2671fc66c81dc9f69d320ee2420f8f`
- Hosted CI: HomeControl CI run `39183220588` — success

These papers distinguish among:

- implemented and software-tested behavior;
- implemented but physically unverified behavior;
- simulated/mock-only behavior;
- planned behavior;
- superseded design decisions.

## White papers

- [Channel metadata, rooms, HVAC semantics and bridges](CHANNEL_METADATA_AND_BRIDGES.md)

- [System Architecture](HOMECONTROL_SYSTEM_WHITE_PAPER.md)
- [Implementation Status](IMPLEMENTATION_STATUS.md)
- [Life-Safety and Safety Arbitration](LIFE_SAFETY_AND_ARBITRATION.md)
- [Network, Communications, and Supervision](NETWORK_AND_HEARTBEAT.md)
- [Hardware Modules and I/O](HARDWARE_MODULES_AND_IO.md)
- [Security, Authentication, and Updates](SECURITY_AUTH_AND_UPDATES.md)
- [Commissioning and Validation Manual](COMMISSIONING_AND_VALIDATION.md)
- [Glossary and Acronyms](GLOSSARY.md)

## Documentation policy

The white papers describe what the current repository and approved architecture actually support. Historical documents under `09_documentation/` remain useful design records, but where they conflict with these white papers or the current audited source, they are historical rather than authoritative.

No hardware is considered physically commissioned solely because software tests pass. Physical commissioning status is tracked separately from software completeness.

## Current documentation-freeze baseline

The software baseline is considered ready for documentation freeze and controlled RCM bench testing. This does not mean the installed physical system is commissioned.

Known physical gaps remain documented in the implementation-status and commissioning papers.

# HomeControl White Papers

This directory is the authoritative white-paper set for the HomeControl project beginning with the audited 2026-10-18/19 software baseline.

## Status

Draft branch: `docs/whitepaper-refresh-2026-10-18`

Code baseline used for the initial draft:

- Repository: `pengels22/HomeControl`
- Commit: `6fc4179c3a2671fc66c81dc9f69d320ee2420f8f`
- Previous audited baseline: `5152d2a02a9cb9008a382a7ced920969130da252`

These papers distinguish among:

- implemented and software-tested behavior;
- implemented but physically unverified behavior;
- simulated/mock-only behavior;
- planned behavior;
- superseded design decisions.

## White papers

- [System Architecture](HOMECONTROL_SYSTEM_WHITE_PAPER.md)
- [Implementation Status](IMPLEMENTATION_STATUS.md)
- [Glossary and Acronyms](GLOSSARY.md)

## Documentation policy

The white papers describe what the current repository and approved architecture actually support. Historical documents under `09_documentation/` remain useful design records, but where they conflict with these white papers or the current audited source, they are historical rather than authoritative.

No hardware is considered physically commissioned solely because software tests pass. Physical commissioning status is tracked separately from software completeness.

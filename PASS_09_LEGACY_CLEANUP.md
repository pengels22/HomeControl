# Pass 9 legacy cleanup

SIM and legacy RMC compatibility remain intentionally retained because this
repository still contains active rollback, firmware-package, management-view,
and historical sensor decoding paths. RCM (relay controller) is unrelated and
was not removed or renamed.

## Retained compatibility surfaces

- SIM/RMC configuration and inventory parsers used by existing installations.
- RMC telemetry decoding and firmware package validation used by tests and
  rollback tooling.
- Existing management adapters and historical database rows/audit evidence.
- Update artifact policy entries needed to reject or roll back old targets.

## New-install behavior

The production PNL workflow registers panels through `/api/v1/pnl-production`
and does not depend on SIM or RMC. Fresh panel configuration uses canonical MAC
identity, HCM areas, published dashboards, and HCM logical commands. SIM/RMC
deprecation metadata from migration 026 remains the retirement gate; applied SQL
history is not rewritten.

Final deletion requires an inventory proving no deployed consumer remains and a
separate rollback window. No live SIM/RMC service was disabled in Pass 9.

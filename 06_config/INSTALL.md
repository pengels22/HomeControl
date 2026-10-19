# HomeControl Installation and Deployment

This file describes the current deployment entry points.

Architecture authority: [HomeControl white papers](../09_documentation/whitepapers/README.md).

## Preferred deployment path

HomeControl uses the unified deployment framework under `06_config/10_Common`.

Mac/operator CLI examples:

```sh
homecontrol status
homecontrol inventory
homecontrol preflight --remote
homecontrol verify
homecontrol verify --remote
homecontrol deploy --dry-run --release <full-sha>
homecontrol deploy --target <target> --release <full-sha> --yes
homecontrol history
```

Live state-changing deployment requires explicit target selection and confirmation.

A full immutable Git SHA is preferred for managed releases.

## Current target classes

The package manifests model:

- Jetson HCM Docker deployment;
- Conflict Heartbeat V3;
- LAB1 simulation;
- Linux modules SIM/LCM/RCM/PNL;
- RMC firmware as a non-Linux target.

RMC firmware is not installed through the generic Linux package path.

## Jetson HCM

The verified development Jetson uses:

- HCM in Docker;
- PostgreSQL in a separate Docker container;
- persistent data under `/srv/hcm-data`;
- host-native Heartbeat V3;
- systemd-managed service lifecycle.

Do not use the old native virtual-environment installer to repair or upgrade the running Jetson.

Use:

[Jetson operations guide](../09_documentation/JETSON_OPERATIONS.md)

## Linux field modules

Linux module packages remain under:

- `06_config/02_SIM`
- `06_config/03_LCM`
- `06_config/04_RCM`
- `06_config/05_PNL`

Their manifests and hardware profiles must validate before deployment.

Repository defaults remain nonphysical.

## Network baseline

Current development/control and supervision traffic uses VLAN 20.

VLAN 40 is a future production-control placeholder whose subnet is not yet approved.

VLAN 60 is not part of the current approved architecture.

Do not invent module addresses or migrate networks as part of an ordinary application deployment.

## IO mode

Modules support explicit hardware modes.

The safe default is simulated operation.

`io.mode: auto` resolves to simulated.

Real mode must be deliberately selected and does not bypass commissioning gates.

## Physical-output safety

Deploying code must never, by itself:

- mark a module COMMISSIONED;
- enable `physical_output_enabled`;
- enable an output section's `real_output_enabled`;
- select an unknown Linux I2C device;
- execute HIL tests.

Physical commissioning is a separate process:

[Commissioning and Validation Manual](../09_documentation/whitepapers/COMMISSIONING_AND_VALIDATION.md)

## Database migrations

HCM database migrations are explicit and separate from ordinary startup.

Use:

```sh
10_scripts/homecontrol-db status
10_scripts/homecontrol-db migrate
```

Live migration requires a reviewed deployment plan and verified backup.

## Secrets

Do not store in Git:

- private keys;
- passwords;
- update authentication secrets;
- heartbeat HMAC secrets;
- database credentials;
- bearer tokens;
- device certificates containing private material.

## RMC firmware

The approved update path is:

HCM -> SIM -> CAN -> RMC

Physical RMC bootloader transfer remains intentionally unavailable until the real bootloader/ACK/retry/verification transport is implemented and bench validated.

## Simulator

The local simulator can be started with:

```sh
.venv/bin/python 10_scripts/simulate_homecontrol.py
```

Simulation must not be described as physical hardware validation.

## Legacy installers

Some package-local installer scripts remain for compatibility.

They are not the deployment authority for the verified Jetson and should not be used as a substitute for the unified deployment framework.

# HCM-Controlled Module Role Switching

Status: repository implementation plan and prototype. Do not deploy to the
Jetson or LAB1 without explicit approval. No physical I/O is enabled by this
work.

## Architecture

Role switching separates three concepts:

- Permanent device identity: normalized hardware device ID such as LAB1
  `2ccf675d3414`.
- Registered module type: the existing `modules.module_type` value used by the
  current module registry and compatibility paths.
- Operational role: `UNASSIGNED`, `RCM`, `SIM` or `LCM`, reported by the module
  heartbeat and managed through `module_role_transitions`.

`UNASSIGNED` is not added to the physical module-type enum. Existing RCM, SIM,
LCM and PNL records remain compatible.

## Authorization

Only authenticated HCM `ADMIN` users may request a role change. The API rejects:

- non-admin users;
- requests without explicit confirmation;
- unsupported roles;
- devices not explicitly enabled for role switching;
- modules without an authenticated online control session;
- active logical-device bindings that require manual compatibility review.

LAB1 is the only initially enabled device.

## Protocol

HCM uses the existing mTLS-authenticated framed JSON module session. It sends a
normal `command` frame with the role-transition operation ID as `request_id`:

```json
{
  "type": "command",
  "request_id": "<operation-id>",
  "payload": {
    "op": "set_module_role",
    "operation_id": "<operation-id>",
    "device_id": "2ccf675d3414",
    "requested_role": "SIM",
    "simulation_required": true
  }
}
```

The module acknowledgement only moves the transition to `ACCEPTED` or
`REJECTED`. HCM marks success only after a later heartbeat or state report
confirms the requested role with `simulation: true` and
`physical_outputs_enabled: false`.

## State Machine

Persisted statuses:

- `PENDING`
- `SENT`
- `ACCEPTED`
- `APPLYING`
- `CONFIRMED`
- `REJECTED`
- `TIMED_OUT`
- `FAILED`

Only one active transition per device is allowed. Expired active transitions are
marked `TIMED_OUT` before a new request is accepted.

## Database

Migration `08_database/005_module_role_switching.sql` adds
`module_role_transitions`. It is additive and repeatable. The preflight
`08_database/005_module_role_switching_preflight.sql` reports if LAB1 is absent,
duplicated, or has active bindings that require manual review before role
switching.

No production migration has been run by this repository change.

## Dashboard and API

API endpoints:

- `GET /api/v1/module-roles`
- `GET /api/v1/module-role-transitions/{operation_id}`
- `POST /api/v1/modules/{device_id}/role`

The dashboard shows LAB1 role-management fields in the Devices area and requires
a browser confirmation before submitting a role request.

## LAB1 Safety

LAB1 remains permanently preserved:

- Hostname remains `lab1`.
- IP remains `192.168.20.36`.
- VLAN remains 20.
- HCM sends config, not network/hostname assignment, to LAB1.
- Physical outputs remain inhibited in every operational role.

The repository-provided helper `10_scripts/lab1_role_agent.py` is safe for
manual deployment. It validates device ID, frame `request_id`, payload
`operation_id`, role and `simulation_required`, atomically updates the existing
`role` field in `/opt/homecontrol-lab/state/module.json`, preserves `device_id`,
`hostname`, `simulation`, `physical_outputs_enabled` and `commissioned`, keeps
the state file owned as before with `0644` permissions, and does not touch
hostname, network, VLAN, GPIO, relays, dimmers, CAN, I2C, SPI or other physical
interfaces. `lab_agent.py` continues to report `state["role"]` as the HCM
heartbeat field `lab_role`.

## Manual LAB1 Installation Outline

Do not run this until LAB1 maintenance is approved.

```sh
sudo install -m 0755 10_scripts/lab1_role_agent.py /opt/homecontrol-lab/lab1_role_agent.py
sudo chown root:root /opt/homecontrol-lab/lab1_role_agent.py
sudo systemctl stop homecontrol-lab.service
# Apply the minimal integration shown in:
# 10_scripts/lab1_agent_set_module_role.patch
# It replaces only the set_module_role case inside the current
# simulation_commands_disabled command handling. All other commands stay rejected.
python3 -m py_compile /opt/homecontrol-lab/lab1_role_agent.py /opt/homecontrol-lab/lab_agent.py
sudo systemctl start homecontrol-lab.service
sudo systemctl status homecontrol-lab.service --no-pager
```

Rollback is restoring the previous `/opt/homecontrol-lab/lab_agent.py` and
removing the helper, then restarting `homecontrol-lab.service`. Do not change
certificates, hostname, networking or system packages as part of rollback.

## Jetson Deployment Boundaries

Deployment requires an approved HCM maintenance window:

1. Run PostgreSQL migration preflight on a copy or approved live maintenance
   context.
2. Back up the live PostgreSQL database.
3. Apply migration `005` only after review.
4. Build a new HCM image from an approved commit.
5. Preserve the currently verified HCM rollback image/container,
   `hcm-control`, `hcm-internal`, isolated PostgreSQL, Heartbeat V3 and
   watchdog services.
6. Recreate only the HCM application container if approved.

Do not restart PostgreSQL, Heartbeat V3, watchdog services, networking or LAB1
as part of repository development.

## Verification

Required before declaring deployment complete:

- API rejects non-admin role requests.
- API rejects nonapproved device IDs.
- API rejects active-binding role switches.
- LAB1 receives a command over the existing mTLS session.
- LAB1 acknowledges acceptance.
- HCM stays `ACCEPTED` until heartbeat confirms the role.
- HCM marks `CONFIRMED` only when heartbeat reports the requested role,
  `simulation=true` and `physical_outputs_enabled=false`.
- Dashboard reflects pending and final status.
- No physical output, network, hostname, VLAN or reboot action occurs.

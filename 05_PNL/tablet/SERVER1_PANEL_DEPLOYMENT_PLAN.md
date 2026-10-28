# Server1 HomeControl Panel API deployment plan

Status: reviewed and corrected; staged validation passed; live deployment not performed.

## Root cause

The live Caddy site has no `/panel/*` handlers. The running `sonic_ha_bridge.py` only handles `/voice-command`; Caddy's catch-all sends `/panel/config` to Whisper, which returns HTTP 404.

## Exact files to change

On Server1, only these files are changed:

- `/opt/sonic-ha-bridge/sonic_ha_bridge.py` — additive import and guarded `/panel/*` branches; existing voice code remains intact.
- `/opt/sonic-ha-bridge/panel_api.py` — new panel API module.
- `/etc/sonic-ha/panel_config_living_room.json` — new exact five-entity configuration.
- `/etc/caddy/Caddyfile` — four panel reverse-proxy handlers.

The systemd unit is not changed. Whisper, policy, Home Assistant, and entity configuration are not changed.

## Final Caddy handlers

These handlers are inserted before the existing `/voice-command` handler:

```caddyfile
# sonic-panel-api-installed
# Authentication is performed by the bridge with SONIC_FIRE7_TOKEN.
# Do not use /authorize here: it is microphone-mute-gated.
handle /panel/config {
    reverse_proxy 127.0.0.1:8767
}
handle /panel/states {
    reverse_proxy 127.0.0.1:8767
}
handle /panel/action {
    reverse_proxy 127.0.0.1:8767
}
handle /panel/health {
    reverse_proxy 127.0.0.1:8767
}
```

The existing `/voice-command` and `/transcribe` handlers retain their current `forward_auth 127.0.0.1:8766 { uri /authorize }` blocks. Panel authentication is independent of microphone mute but still requires the dedicated Fire 7 bearer token inside the bridge.

## Pre-deployment backup with one timestamp

Run once from the workstation; use the same `DEPLOY_TS` for every backup:

```sh
DEPLOY_TS=$(date +%Y%m%d-%H%M%S)
BACKUP_DIR="/var/backups/sonic-panel/${DEPLOY_TS}"
ssh server1 "sudo install -d -m 700 '${BACKUP_DIR}'"
ssh server1 "sudo env DEPLOY_TS='${DEPLOY_TS}' BACKUP_DIR='${BACKUP_DIR}' sh -s" <<'REMOTE'
set -eu
printf 'deployment_timestamp=%s\n' "$DEPLOY_TS" > "$BACKUP_DIR/manifest.txt"
for f in /etc/caddy/Caddyfile /opt/sonic-ha-bridge/sonic_ha_bridge.py /opt/sonic-ha-bridge/panel_api.py /etc/sonic-ha/panel_config_living_room.json; do
    if test -e "$f"; then
        printf 'EXISTED %s\n' "$f" >> "$BACKUP_DIR/manifest.txt"
        cp -a "$f" "$BACKUP_DIR/"
    else
        printf 'ABSENT %s\n' "$f" >> "$BACKUP_DIR/manifest.txt"
    fi
done
systemctl --no-pager --full status sonic-ha-bridge caddy sonic-policy sonic-whisper > "$BACKUP_DIR/service-status.txt"
systemctl cat sonic-ha-bridge.service > "$BACKUP_DIR/sonic-ha-bridge.service.txt"
sha256sum /etc/caddy/Caddyfile /opt/sonic-ha-bridge/sonic_ha_bridge.py > "$BACKUP_DIR/live-sha256.txt"
REMOTE
ssh server1 "sudo cat '${BACKUP_DIR}/manifest.txt'"
```

The manifest records files that were absent before deployment. Do not overwrite the live files until the staged candidates pass all checks.

## Build and stage candidates

```sh
STAGE_DIR=$(mktemp -d /private/tmp/sonic-panel-deploy.XXXXXX)
scp server1:/opt/sonic-ha-bridge/sonic_ha_bridge.py "$STAGE_DIR/sonic_ha_bridge.py"
scp server1:/etc/caddy/Caddyfile "$STAGE_DIR/Caddyfile"
cp server1/panel_api.py "$STAGE_DIR/panel_api.py"
cp panel_config_living_room.json "$STAGE_DIR/panel_config_living_room.json"
python3 server1/apply_panel_integration.py "$STAGE_DIR/sonic_ha_bridge.py" "$STAGE_DIR/Caddyfile"
scp "$STAGE_DIR/sonic_ha_bridge.py" server1:/tmp/sonic-panel-${DEPLOY_TS}.py
scp "$STAGE_DIR/panel_api.py" server1:/tmp/panel_api-${DEPLOY_TS}.py
scp "$STAGE_DIR/panel_config_living_room.json" server1:/tmp/panel_config-${DEPLOY_TS}.json
scp "$STAGE_DIR/Caddyfile" server1:/tmp/Caddyfile-${DEPLOY_TS}
```

## Staged validation

```sh
ssh server1 "sudo install -d -m 700 /tmp/sonic-panel-${DEPLOY_TS}; sudo install -m 755 /tmp/sonic-panel-${DEPLOY_TS}.py /tmp/sonic-panel-${DEPLOY_TS}/sonic_ha_bridge.py; sudo install -m 644 /tmp/panel_api-${DEPLOY_TS}.py /tmp/sonic-panel-${DEPLOY_TS}/panel_api.py; sudo install -m 644 /tmp/panel_config-${DEPLOY_TS}.json /tmp/sonic-panel-${DEPLOY_TS}/panel_config_living_room.json"
ssh server1 "sudo env PYTHONPATH=/tmp/sonic-panel-${DEPLOY_TS} SONIC_API_TOKEN=dummy SONIC_FIRE7_TOKEN=dummy /opt/sonic-whisper/venv/bin/python -m py_compile /tmp/sonic-panel-${DEPLOY_TS}/panel_api.py /tmp/sonic-panel-${DEPLOY_TS}/sonic_ha_bridge.py"
ssh server1 "sudo env PYTHONPATH=/tmp/sonic-panel-${DEPLOY_TS} SONIC_API_TOKEN=dummy SONIC_FIRE7_TOKEN=dummy /opt/sonic-whisper/venv/bin/python -c 'import sonic_ha_bridge, panel_api; print(\"staged_imports_ok\")'"
ssh server1 "sudo caddy validate --config /tmp/Caddyfile-${DEPLOY_TS} --adapter caddyfile"
```

The staging applier refuses source that does not match the current bridge layout, refuses double application, verifies the voice route markers remain, and verifies the two existing `forward_auth` blocks remain. The staging source import uses the actual Server1 Python 3.14 environment.

## Mock security and action tests

Run locally before activation:

```sh
python3 -m py_compile server1/panel_api.py server1/test_panel_api.py server1/apply_panel_integration.py
python3 -m unittest discover -s server1 -p 'test_*.py' -v
```

These tests use mocked HA responses and cover config shape, batched states, fixed service mapping, malformed JSON, missing fields, extra service fields, unauthorized entities, unsupported actions, climate ranges/modes, and authentication helpers. No live `POST /panel/action` is used.

## Install and activate after review

```sh
ssh server1 "sudo install -m 755 /tmp/panel_api-${DEPLOY_TS}.py /opt/sonic-ha-bridge/panel_api.py"
ssh server1 "sudo install -o root -g root -m 640 /tmp/panel_config-${DEPLOY_TS}.json /etc/sonic-ha/panel_config_living_room.json"
ssh server1 "sudo install -m 755 /tmp/sonic-panel-${DEPLOY_TS}.py /opt/sonic-ha-bridge/sonic_ha_bridge.py"
ssh server1 "sudo install -m 644 /tmp/Caddyfile-${DEPLOY_TS} /etc/caddy/Caddyfile"
ssh server1 "sudo /opt/sonic-whisper/venv/bin/python -m py_compile /opt/sonic-ha-bridge/panel_api.py /opt/sonic-ha-bridge/sonic_ha_bridge.py"
ssh server1 "sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile"
ssh server1 "sudo systemctl restart sonic-ha-bridge && sudo systemctl reload caddy"
ssh server1 'sudo systemctl is-active sonic-ha-bridge caddy sonic-policy sonic-whisper'
```

Only `sonic-ha-bridge` is restarted; Caddy is reloaded, not restarted. No unrelated service is touched.

## Read-only API verification

Use the existing Fire 7 credential without printing it:

```sh
SONIC_TOKEN=$(sed -n 's/^SONIC_API_TOKEN=//p' /path/to/credential)
curl --cacert /path/to/sonic-caddy-root.crt -sS -D /tmp/panel.headers -H "Authorization: Bearer $SONIC_TOKEN" https://192.168.1.6:8443/panel/config -o /tmp/panel.config.json
curl --cacert /path/to/sonic-caddy-root.crt -sS -H "Authorization: Bearer $SONIC_TOKEN" https://192.168.1.6:8443/panel/states -o /tmp/panel.states.json
curl --cacert /path/to/sonic-caddy-root.crt -sS -H "Authorization: Bearer $SONIC_TOKEN" https://192.168.1.6:8443/panel/health
curl --cacert /path/to/sonic-caddy-root.crt -sS -H "Authorization: Bearer $SONIC_TOKEN" https://192.168.1.6:8443/health
curl --cacert /path/to/sonic-caddy-root.crt -sS -H "Authorization: Bearer $SONIC_TOKEN" https://192.168.1.6:8443/mic-policy
```

Expected: panel reads and health HTTP 200; five configured states; existing health and microphone policy remain available. Missing and dummy credentials must return HTTP 401 for all panel routes. Do not issue live action requests during this validation.

The following no-side-effect checks verify Caddy routing and bridge authentication together:

```sh
for path in config states health; do
  curl --cacert /path/to/sonic-caddy-root.crt -sS -o /dev/null -w "/panel/$path without auth: %{http_code}\n" "https://192.168.1.6:8443/panel/$path"
done
```

Each response must be HTTP 401. A valid-token read of `/panel/config` and `/panel/states` must then return HTTP 200. No action POST is used.

## Complete rollback

Use the exact `DEPLOY_TS` and manifest recorded before deployment:

```sh
DEPLOY_TS=YYYYMMDD-HHMMSS
BACKUP_DIR="/var/backups/sonic-panel/${DEPLOY_TS}"
ssh server1 "sudo systemctl stop sonic-ha-bridge"
ssh server1 "sudo cp -a '${BACKUP_DIR}/Caddyfile' /etc/caddy/Caddyfile"
ssh server1 "sudo cp -a '${BACKUP_DIR}/sonic_ha_bridge.py' /opt/sonic-ha-bridge/sonic_ha_bridge.py"
ssh server1 "if grep -q '^EXISTED /opt/sonic-ha-bridge/panel_api.py$' '${BACKUP_DIR}/manifest.txt'; then sudo cp -a '${BACKUP_DIR}/panel_api.py' /opt/sonic-ha-bridge/panel_api.py; else sudo rm -f /opt/sonic-ha-bridge/panel_api.py; fi"
ssh server1 "if grep -q '^EXISTED /etc/sonic-ha/panel_config_living_room.json$' '${BACKUP_DIR}/manifest.txt'; then sudo cp -a '${BACKUP_DIR}/panel_config_living_room.json' /etc/sonic-ha/panel_config_living_room.json; else sudo rm -f /etc/sonic-ha/panel_config_living_room.json; fi"
ssh server1 "sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile && sudo systemctl reload caddy && sudo systemctl start sonic-ha-bridge"
ssh server1 'sudo systemctl is-active sonic-ha-bridge caddy sonic-policy sonic-whisper'
```

If any validation fails before activation, leave the live files untouched and remove only the timestamped `/tmp/sonic-panel-*` staging artifacts.

## Current review results

- Live Python: `/usr/bin/python3.14`, Python 3.14.4; protected environment contains `SONIC_API_TOKEN` and `SONIC_FIRE7_TOKEN`.
- Existing bridge source imports and voice route markers were preserved in staging.
- Candidate Caddyfile validates with `--adapter caddyfile`.
- Staged bridge route/auth checks with mocked panel handlers returned 401 without the Fire 7 token, 200 with it for panel reads/actions, and preserved the existing voice path as a separate route.
- Existing live services are active.
- No live Server1 files or services were modified during this review.

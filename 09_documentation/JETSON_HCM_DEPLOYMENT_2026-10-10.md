# Jetson Xavier NX HCM Deployment Runbook

**Verified:** 2026-10-10 on the Jetson Xavier NX development host. This documents an **existing working test deployment**, not a production-grade or turnkey installer. Commands below are for inspection/recovery unless explicitly marked as commissioning examples. Do not copy live credentials into Git.

## Proven status and scope

- Jetson Xavier NX Developer Kit, Ubuntu 18.04.6 LTS / L4T 32.6.1, Linux 4.9.253-tegra, host Python 3.6.9.
- HCM application runs **inside Docker with Python 3.13**, not the Jetson host interpreter. Image name: `homecontrol-hcm:phase3`; container: `hcm-test`; UI/API bound to `192.168.20.27:8080` on VLAN 20.
- PostgreSQL 16 runs as `hcm-postgres` on a separate, isolated Docker network. Its database persists at `/srv/hcm-data/postgres`, on an ext4 USB filesystem.
- Independent Unified Heartbeat V3 runs as the **host** `hcm-heartbeat.service` using Python 3.6 and TCP 6004; it is not part of the HCM Docker container. Conflict is `192.168.20.26`; Jetson WLAN is `192.168.20.27`. The future heartbeat-only VLAN 60 migration has **not** occurred.
- Full Jetson reboot on 2026-10-10 verified four active services, mounted USB, running HCM and Postgres containers, restored return routing and successful HCM startup; user subsequently confirmed dashboard loaded. This does **not** establish crash recovery, hardware GPIO safety, TLS, or backups.
- Network/storage addresses here describe this specific development host; they are **not** portable defaults.

## Live network layout

| Interface/network | Address or subnet | Role |
| --- | --- | --- |
| Jetson `eth0` | `192.168.1.63` | Ethernet / VLAN 1 |
| Jetson `wlan0` | `192.168.20.27` | Control and test dashboard / VLAN 20 |
| HCM `hcm-control` | `172.19.0.0/16`, HCM `172.19.0.2` at verification | Ordinary Docker bridge; published HCM API |
| Private `hcm-internal` | `172.18.0.0/16`, HCM `172.18.0.3` at verification | Docker `--internal` network for HCM ↔ database |
| Postgres | `hcm-internal` only | No published PostgreSQL host port |
| Mac used for validation | `192.168.1.241` | Currently the *only* destination matched by HCM return-routing rule |
| Wi-Fi route table 200 | via `192.168.20.1 dev wlan0` | Return traffic for the verified client |

Docker networks were automatically given subnets, not created with user-configured IPAM subnets. **Do not use `docker network connect --ip ...` on these existing networks**: Docker rejected it with “user specified IP address is supported only when connecting to networks with user configured subnets.” The current `172.19.0.2` address is *dynamic*, not reserved. The routing script looks up the live HCM control address.

`192.168.20.27:8080` must remain accessible only to trusted, authorized development clients. The current HTTP endpoint has no TLS; passwords and bearer tokens are sent in plaintext. Do not forward it to the internet or treat commissioning credentials as production credentials.

## Files and services on the Jetson

| Path / name | Purpose |
| --- | --- |
| `~/HomeControl` | Jetson Git checkout |
| `/tmp/hcm-docker-build` | Temporary image build context made from `git archive HEAD` |
| `/etc/hcm/hcm.env` | Root-readable deployment environment, contains `HCM_DATABASE_URL`; **secret, do not commit** |
| `/etc/hcm/postgres-password` | PostgreSQL password file, root-only; **secret, do not commit** |
| `/srv/hcm-data` | Mounted ext4 USB volume, label `HCM_DATA`; expected filesystem UUID `8c4c9aaf-67e1-4a0c-b05e-3ab2824593ce` |
| `/srv/hcm-data/postgres` | PostgreSQL database bind mount, UID 999, mode 0700 |
| `hcm-postgres.service` | systemd oneshot controlling `hcm-postgres`; includes USB mount dependency and UUID guard |
| `hcm-routing.service` | systemd oneshot that waits for route table 200 with `wlan0` |
| `hcm.service` | systemd oneshot starts/stops `hcm-test` after PostgreSQL readiness |
| `/etc/systemd/system/hcm.service.d/routing.conf` | `ExecStartPost=/usr/local/sbin/hcm-update-routing` |
| `/usr/local/sbin/hcm-update-routing` | Detects live HCM Docker IP and manages priority-1100 policy route |
| `hcm-heartbeat.service` | Independent host-based V3 daemon; do not restart as part of HCM lifecycle |

The USB filesystem is mounted by UUID through `/etc/fstab` with `nofail`. PostgreSQL's systemd unit explicitly requires the mount, binds service lifetime to `srv-hcm\x2ddata.mount`, and checks the expected UUID before starting. This was verified on normal reboot, **not** by unplug/power-loss fault injection. Flash USB is a temporary PostgreSQL medium; durability, wear, and power-loss behavior remain concerns.

## Rebuild / replace HCM image (maintenance window)

The HCM image is made from the checked-out commit, *not* uncommitted working-tree changes. Confirm Git revision and review changes first:

```sh
cd ~/HomeControl
git status --short
git pull --ff-only origin main
git log -1 --oneline

rm -rf /tmp/hcm-docker-build
mkdir -p /tmp/hcm-docker-build
git archive HEAD | tar -x -C /tmp/hcm-docker-build
cat > /tmp/hcm-docker-build/Dockerfile <<'DOCKERFILE'
FROM python:3.13-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/opt/HomeControl
WORKDIR /opt/HomeControl
COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt
COPY . .
USER 10001:10001
EXPOSE 8080
CMD ["python", "-m", "uvicorn", "01_HCM.main:app", "--host", "0.0.0.0", "--port", "8080"]
DOCKERFILE
sudo docker build -t homecontrol-hcm:phase3 /tmp/hcm-docker-build
```

The running container does **not** automatically use a rebuilt image. When replacing it, preserve a known-working image and rollback container until the new instance is verified. Stop `hcm.service` before changing `hcm-test`. Use `docker create` with `--restart no`, `--network hcm-control`, `--env-file /etc/hcm/hcm.env`, and `-p 192.168.20.27:8080:8080`; then **connect `hcm-internal` before `docker start`** to avoid database DNS/startup failure. Do not expose database port 5432 or attach Postgres to the external control network. Apply `sudo systemctl start hcm.service` after preparing the replacement; the start hook refreshes routing after Docker assigns the container IP. Verify network memberships and logs.

The running app code was corrected in Git: `01_HCM/auth.py` uses integer interval multiplication for session, challenge, and pairing-key TTL parameters (asyncpg rejected integers cast through `::text`), and `01_HCM/www/app.css` has `[hidden] { display: none !important; }` for proper post-login visibility. Do not patch container source manually: a rebuild/recreation would lose it.

**Legacy alternatives:** `docker-compose.yml` in the repo currently has a development password and exposes PostgreSQL on 5432. `07_servises/systemd/homecontrol-hcm.service` describes native-venv deployment. **Neither represents this Jetson deployment and neither should be applied to the live host.**

## Systemd dependencies (current implementation)

- `hcm-postgres.service` is enabled, `Type=oneshot`, `RemainAfterExit=yes`, requires a mounted verified USB filesystem and starts/stops `hcm-postgres` via Docker.
- `hcm-routing.service` is enabled, `Type=oneshot`, `RemainAfterExit=yes`; waits up to ~60 seconds for table 200 to contain a `wlan0` route; ordered before `hcm.service`.
- `hcm.service` is enabled, `Type=oneshot`, `RemainAfterExit=yes`; requires Docker, Postgres and routing; checks `pg_isready -U homecontrol -d homecontrol` up to 30 times with 2-second sleeps; runs `docker start hcm-test` / `docker stop -t 20 hcm-test`.
- `ExecStartPost` on `hcm.service` calls `hcm-update-routing` after start, when Docker has assigned addresses.
- `hcm-heartbeat.service` is independently enabled; don't add `Requires=` or `PartOf=` from HCM to heartbeat.

**Limitations:** the oneshot units report `active (exited)` after Docker launch even if their containers crash later. Automatic crash recovery / health monitoring is **not implemented**. `ExecStartPost` verifies an IP/route, not FastAPI health. Full loss-of-USB supervision, DB recovery, backups and alerting are still pending.

## Return-route policy and known limits

A Mac at `192.168.1.241` connects from VLAN 1 to the published Jetson Wi-Fi address on VLAN 20. Inbound SYN entered `wlan0`, Docker DNAT forwarded it to `172.19.0.2`, and container SYN-ACKs were incorrectly routed out `eth0` after reverse NAT. This caused TCP/HTTP timeouts even though the container and bridge returned HTTP 200. `tcpdump` on each interface confirmed this. Policy table 200 routes the connection back over `wlan0`.

`/usr/local/sbin/hcm-update-routing` currently:
1. Gets `hcm-test`'s current IP on `hcm-control` with `docker inspect`.
2. Requires a route through `wlan0` in table 200.
3. Deletes existing rules at preference 1100.
4. Adds `ip -4 rule add pref 1100 from <live-hcm-ip>/32 to 192.168.1.241/32 lookup 200`.
5. Flushes the route cache.

This policy is restricted to that **single Mac IP**. Other clients, or the Mac after DHCP renumbering, are not covered. Expand only after agreeing on authorized client ranges and access controls. Rule preference 1100 is dedicated to HCM. The script must be present on the Jetson; it is **not automatically deployed from Git**.

## Read-only operational checks

```sh
for s in hcm-heartbeat hcm-postgres hcm-routing hcm; do
    printf '%-18s ' "$s"; systemctl is-active "$s"
done
findmnt /srv/hcm-data
sudo docker ps --filter name=hcm
sudo docker inspect hcm-test --format '{{range $name, $net := .NetworkSettings.Networks}}{{$name}} = {{$net.IPAddress}}{{println}}{{end}}'
ip -4 rule show | grep 1100
ip -4 route show table 200
sudo docker logs --tail 20 hcm-test
sudo docker exec hcm-test python -c 'import httpx; print(httpx.get("http://127.0.0.1:8080/api/v1/health",timeout=5).status_code)'
```

The application health endpoint may return 200 without proving the whole safety system is operational. Independently verify `systemctl is-active hcm-heartbeat` and the V3 status endpoint. The login dashboard was validated from a Mac after the 2026-10-10 reboot.

## Recovery and rollback boundaries

- `sudo systemctl restart hcm.service` performs a controlled HCM-only restart and reruns the routing hook; **it must not restart heartbeat**.
- If HCM loses access but logs show `Application startup complete`, inspect both HCM Docker networks, live control IP, policy rule 1100, table 200 and outbound interface before editing firewall rules.
- If PostgreSQL cannot start, check `findmnt /srv/hcm-data` and the expected UUID first; **never** create a replacement database on the unmounted Jetson root.
- A previous container named `hcm-previous` and image tag `homecontrol-hcm:phase3-backup` were retained during commissioning; confirm they still exist before relying on them for rollback.
- Do not blindly reapply `08_database/schema.sql` migrations to an existing database; schema was installed during commissioning. Follow migration procedures when adding future migrations.
- No automatic backup verification or unattended crash recovery is in place yet.

## Remaining hardening before production

- Replace temporary commissioning credentials, revoke prior sessions, enforce strong secrets, HTTPS/TLS and proper client access restrictions. Production WebAuthn adapter remains incomplete.
- Introduce **continuous** HCM and PostgreSQL health supervision with bounded restart attempts and alerts; ensure heartbeat stays independent.
- Revisit PostgreSQL media (USB flash is a weak durability choice), mount disappearance/power loss, restore tests and backup schedule.
- Configure reliable access for other authorized devices without fragile single-client routing; future VLAN 40 and 60 migrations remain deferred.
- Connect/control actual hardware and safety pathways only under separately reviewed commissioning procedures; GPIO, hardwired fire path and relay outputs have **not** been validated by this deployment.
- Keep host systemd units, routing script, secrets template and Docker build/replace procedure reproducible under version control, without publishing live secrets.

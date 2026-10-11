# HCM Module mTLS Identity Deployment Plan

Status: prepared for review. Do not deploy these steps until the operator
approves a maintenance window. This document does not contain private keys,
passwords, bearer tokens or live environment-file contents.

## Scope

The HCM module listener on TCP 6501 must only be published after verified
mutual TLS is enabled. Each module client certificate must contain exactly one
device URI SAN:

```text
urn:homecontrol:device:<normalized-device-id>
```

For LAB1 the approved URI is:

```text
urn:homecontrol:device:2ccf675d3414
```

The HomeControl CA private key remains on the Mac. Never copy it to the Jetson,
LAB1, Git or Docker images.

## PKI Inputs

Expected files on the Mac:

- CA certificate: `~/HomeControl-PKI/ca/homecontrol-ca.crt`
- HCM certificate: `~/HomeControl-PKI/hcm/hcm-server.crt`
- HCM private key: `~/HomeControl-PKI/hcm/hcm-server.key`
- LAB1 certificate: `~/HomeControl-PKI/lab1/lab1-client.crt`
- LAB1 private key: `~/HomeControl-PKI/lab1/lab1-client.key`

Before deployment, inspect certificates locally:

```sh
openssl x509 -in ~/HomeControl-PKI/ca/homecontrol-ca.crt -noout -subject -issuer -dates
openssl x509 -in ~/HomeControl-PKI/hcm/hcm-server.crt -noout -subject -issuer -dates -ext subjectAltName
openssl x509 -in ~/HomeControl-PKI/lab1/lab1-client.crt -noout -subject -issuer -dates -ext subjectAltName
```

Confirm LAB1 has exactly one device URI SAN and it is
`urn:homecontrol:device:2ccf675d3414`.

## Repository Behavior

HCM registration now rejects a TLS-authenticated module before assignment or
database writes when:

- no client certificate is available;
- the identify payload omits `device_id`;
- the certificate has no device URI SAN;
- the certificate has duplicate device URI SANs;
- the certificate URI has a malformed device ID;
- the certificate device ID differs from the claimed device ID.

When the secure listener guard is enabled, HCM startup rejects an insecure module
listener unless all of these are true:

- `HCM_TLS_ENABLED=true`
- `HCM_TLS_REQUIRE_CLIENT_CERT=true`
- `HCM_MODULE_CERT_IDENTITY_REQUIRED=true`

`HCM_ALLOW_INSECURE_MODULE_LISTENER=true` remains available only for explicit
local development or an approved unpublished staging listener. The repository
default is `false`, so a future HCM start fails fast instead of accidentally
publishing unauthenticated TCP 6501.

## LAB1 Preservation

LAB1 is preserved by device ID:

- Device ID: `2ccf675d3414`
- Hostname: `lab1`
- IP: `192.168.20.36`
- Allowed simulated roles: `RCM`, `SIM`, `LCM`
- Default supervisor role: `UNASSIGNED`

HCM does not treat `UNASSIGNED` as a physical module type. LAB1 is never sent an
assignment frame to rename itself or change IP/VLAN during registration.
Ordinary pool assignment also reserves `192.168.20.36` so another LCM is not
issued LAB1's current address.

Role changes for LAB1 remain a future authorized and audited workflow. Do not
delete or silently reassign logical-device bindings as part of simulator role
switching.

The authorized role-switching prototype is documented separately in
`09_documentation/HCM_MODULE_ROLE_SWITCHING_2026-10-10.md`. It keeps the mTLS
certificate-to-device-ID binding intact and continues to preserve LAB1 hostname,
IP address, VLAN and physical-output inhibition.

## Jetson Staging Plan

These are proposed steps only. Do not run them without approval.

1. Confirm current service and rollback baseline:

```sh
cd ~/HomeControl
git status --short
git log -1 --oneline
systemctl is-active hcm hcm-postgres hcm-heartbeat hcm-watchdog.timer
sudo docker ps --filter name=hcm-test --filter name=hcm-postgres
sudo docker inspect hcm-test --format '{{json .NetworkSettings.Networks}}'
```

2. Copy only public CA and HCM server material to root-readable Jetson paths.
   Do not copy the CA private key. Suggested target layout:

```text
/etc/hcm/pki/homecontrol-ca.crt
/etc/hcm/pki/hcm-server.crt
/etc/hcm/pki/hcm-server.key
```

3. Protect the copied files:

```sh
sudo chown -R root:root /etc/hcm/pki
sudo chmod 0750 /etc/hcm/pki
sudo chmod 0644 /etc/hcm/pki/homecontrol-ca.crt /etc/hcm/pki/hcm-server.crt
sudo chmod 0600 /etc/hcm/pki/hcm-server.key
```

4. Prepare `/etc/hcm/hcm.env` changes without restarting:

```text
HCM_TLS_ENABLED=true
HCM_TLS_CERT=/etc/hcm/pki/hcm-server.crt
HCM_TLS_KEY=/etc/hcm/pki/hcm-server.key
HCM_TLS_CA=/etc/hcm/pki/homecontrol-ca.crt
HCM_TLS_REQUIRE_CLIENT_CERT=true
HCM_MODULE_CERT_IDENTITY_REQUIRED=true
HCM_ALLOW_INSECURE_MODULE_LISTENER=false
HCM_MODULE_HOST=0.0.0.0
HCM_MODULE_PORT=6501
```

5. Build a reviewed image from an approved commit while preserving the Phase 4
   rollback image/container and the two existing Docker networks. Do not alter
   PostgreSQL, storage, Heartbeat V3, watchdog, systemd dependencies or Docker
   network topology.

6. During the maintenance window, recreate only the HCM application container
   with the existing private PostgreSQL network and control network. Publish
   ports only on Jetson Ethernet:

```text
-p 192.168.20.27:8080:8080
-p 192.168.20.27:6501:6501
```

7. Verify before LAB1 attempts to connect:

```sh
sudo docker logs --tail 100 hcm-test
curl -i http://192.168.20.27:8080/api/v1/health
sudo docker exec hcm-test python -m py_compile 01_HCM/registry.py
```

8. Copy LAB1 client certificate and key only to LAB1 during an approved LAB1
   maintenance workflow. This repository task does not access LAB1.

## Rollback Notes

- Keep the previous Phase 4 image and rollback container until mTLS listener
  validation is complete.
- Roll back by stopping the new HCM container and restoring the prior HCM
  container/image through the existing `hcm.service` workflow.
- Do not roll back PostgreSQL migrations automatically. This mTLS change does
  not require a database migration.
- Do not restart or modify `hcm-postgres`, `hcm-heartbeat.service`,
  `hcm-watchdog.service`, `hcm-watchdog.timer`, networking, routing, firewall or
  USB storage as part of module-listener rollback.

## Validation Checklist

- HCM starts only when TLS, client-certificate validation and device URI
  enforcement are all configured.
- TCP 6501 is reachable only at `192.168.20.27:6501`.
- A client without a certificate cannot complete TLS.
- A client certificate without the LAB1 device URI cannot register as LAB1.
- A LAB1 certificate cannot register as another device ID.
- LAB1 registration receives config, not an assignment changing hostname/IP.
- Dashboard/API on `192.168.20.27:8080` continues to work.
- PostgreSQL remains isolated on its private Docker network.
- Heartbeat V3 and watchdog remain active and were not restarted as part of the
  deployment.

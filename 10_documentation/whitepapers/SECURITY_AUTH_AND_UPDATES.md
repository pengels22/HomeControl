# HomeControl Security, Authentication, and Update White Paper

**Audited software baseline:** `544c5c87594d955a2a33e2bac336ae5a536f2463`

## Purpose

This paper describes the implemented security boundaries for HomeControl: user authentication, touchscreen access, module identity, heartbeat authentication, pairing, and software-update trust.

## ACM credential and administration boundary

ACM stores named Master and Standard PIN credentials, up to 16 records, with a
per-record 16-byte random salt and PBKDF2-HMAC-SHA256. PINs are not stored in
plaintext. ACM's embedded administration surface is local HTTP on the trusted
network; it does not claim HTTPS. Administration accepts Master PINs only and
rejects Standard credentials. Sessions use server-side random tokens, a
five-minute idle timeout, HttpOnly cookies, SameSite=Strict, CSRF-protected
POST mutations, login rate limiting, and bounded HTTP requests. Credential
mutations require current Master reauthentication.

Legacy credential records enter a limited reprovision route that creates a new
Master credential rather than importing legacy secrets. Public/configuration
backups exclude PIN values, salts, hashes, session secrets, and other
credential material. ACM firmware updates are USB-only; ACM has no OTA path.

## User authentication

HCM is the central user authority.

Implemented behavior includes:

- PostgreSQL-backed user records;
- ADMIN and READONLY roles;
- PBKDF2-SHA256 password hashing;
- persistent bearer sessions;
- current role and enabled-state validation on authenticated requests;
- session revocation;
- login failure lockout and rate limiting.

Authentication is local-first and does not depend on an external cloud identity provider.

## Touchscreen access

Touchscreen security includes:

- device-specific authentication tokens;
- six-digit PINs;
- scrypt PIN hashing;
- keyed PIN lookup;
- VIEWER, CONTROL, and ADMIN permissions;
- timeout and revocation support.

## Passkeys and WebAuthn

The repository contains challenge-generation and credential scaffolding for passkeys.

Production WebAuthn assertion verification is not yet implemented.

When production verification is unavailable, HCM reports that limitation rather than silently substituting a weaker verifier.

Development-only passkey behavior is gated by development mode.

## Pairing

HCM contains pairing-key infrastructure for securely associating clients with the controller.

Pairing remains centrally verified by HCM. A companion application does not become an independent field-module control authority.

## Module transport identity

The HCM module listener supports:

- TLS;
- client certificates;
- CA validation;
- certificate identity checking.

Production operation is intended to use mutually authenticated TLS.

Current development YAML defaults do not yet enable module TLS, so certificate deployment remains a separate production milestone.

## Stable device identity

Operational device IDs are normalized MAC addresses from designated physical interfaces.

Certificate identity and stable device identity serve different purposes:

- the device ID is a stable operational identifier;
- certificate validation provides cryptographic peer authentication.

A MAC address alone is not a cryptographic proof of identity.

## Unified Heartbeat V3 authentication

Heartbeat V3 supports HMAC-SHA256 request and response authentication.

Validation includes:

- authorized-device registry;
- request/response message authentication;
- timestamp skew limits;
- stable device ID;
- boot ID;
- sequence progression;
- replay rejection;
- expected Conflict Manager identity.

## Update request authentication

The generic update service validates an authenticated request envelope including:

- message authentication;
- operation ID;
- timestamp;
- durable replay protection.

Accepted operation IDs are persisted so a service restart does not erase replay history.

## Artifact trust

Software artifacts are validated using:

- SHA-256 integrity;
- Ed25519 signature verification;
- expected target type;
- hardware-revision compatibility;
- canonical staging-path checks;
- fixed installer selection.

The update framework does not accept arbitrary command strings as installers.

## Post-update verification

HCM records the pre-update module state and requires a newer post-update heartbeat before considering the module returned.

When an expected software version is supplied, a version mismatch is treated as an unsuccessful verification.

## RMC update boundary

Physical RMC firmware update remains intentionally unavailable.

Until the CAN bootloader protocol and acknowledgement flow are implemented and physically validated, physical update mode fails closed.

Simulation can test state-machine behavior without claiming real flash activity.

## Secret handling

Credentials and signing material belong in local deployment files or secret-management mechanisms, not in version control.

Repository safety checks are intended to detect accidental committed credential material.

## Current security gaps

Outstanding work includes:

- production WebAuthn assertion verification;
- deployment and lifecycle management for production mTLS certificates;
- companion-app production authentication/session lifecycle;
- final push-notification delivery security;
- GitHub branch protection enforcement;
- target-specific physical installer validation.

## Repository controls

At the audited baseline, GitHub `main` is not branch-protected.

Before production release, branch protection should require successful HomeControl CI and should prevent destructive force-push/deletion behavior.

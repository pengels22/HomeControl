# Touchscreen PIN Schema Review

Date: 2026-10-17  
Baseline: `eeb576e37a0d1ba77a7046e2b4520ecb1963a286`  
Scope: repository-only review; no database or live service changes

## Current schema

The bootstrap schema is `08_database/schema.sql`; additive changes use numbered SQL files in `08_database/`. No migration runner or ORM migration framework is present. Deployment documentation requires an approved backup and explicit migration execution, so the PIN change is delivered as an additive, idempotent SQL migration and is not run automatically by application startup.

`users` currently contains `id`, unique `username`, web `role` (`ADMIN` or `READONLY`), nullable `password_hash`, nullable `passkey_credential`, `enabled`, and `created_at`. `user_sessions` stores a username, unique SHA-256 hash of an opaque bearer token, a copied web role, creation/expiry timestamps, and optional revocation timestamp. `auth_challenges` is username-scoped and expires/consumes passkey challenges. Existing user passwords use salted PBKDF2-SHA256; password changes revoke existing web sessions.

## Existing semantics and preservation

Web roles remain unchanged: `ADMIN` is required for user administration and device-changing web APIs; `READONLY` can use authenticated read APIs. Touchscreen permissions are a separate `VIEWER`, `CONTROL`, or `ADMIN` capability and do not modify or elevate the web role. Existing users receive `VIEWER` and disabled touchscreen PIN authentication. Existing passwords, passkey material, web roles, and web sessions are preserved.

User creation defaults touchscreen permission to `VIEWER` and leaves PIN authentication disabled. Disabling a user, resetting a PIN, reducing touchscreen permission, or revoking a touchscreen device invalidates related touchscreen sessions. Deleting a user is protected by the existing foreign-key model and cascades related touchscreen sessions.

## Synchronization and trust boundaries

`build_user_snapshot()` currently synchronizes only username, web role, enabled state, and the web password verifier to authenticated modules. PIN hashes, lookup indexes, lookup secrets, touchscreen sessions, and device tokens must remain HCM-only and are explicitly excluded from this payload. Touchscreen production state reads and commands remain HCM-authorized API operations; no module-local PIN verifier is introduced.

The repository did not previously contain a durable touchscreen-device registration table or a device-scoped HTTP credential verifier. The minimal addition is `touchscreen_devices`, containing a permanent device identity, a hash of a provisioned device token, enabled state, permitted module identities, and timestamps. It is device metadata, not a second user directory. Provisioning is administrative/database-controlled; no touchscreen request can create or authorize a device. Native production mode uses a dedicated `HOMECONTROL_TOUCHSCREEN_DEVICE_TOKEN`, never a web bearer token.

## Proposed additive migration

1. Add nullable PIN fields to `users` with safe defaults: scrypt verifier, HMAC lookup value, enabled flag, permission check, changed timestamp, and policy JSON.
2. Add a unique lookup index, allowing one enabled account per PIN lookup value while permitting disabled historical rows to be cleared during disable/reset.
3. Add `touchscreen_devices` with unique permanent identity and token hash, enabled state, permitted module identities, and audit timestamps.
4. Add `touchscreen_sessions` with token hash, user/device references, permission snapshot, idle and absolute expiry, last activity, and revocation fields.
5. Add `touchscreen_rate_limits` for global and per-device progressive backoff.
6. Keep all changes additive and guarded with `IF NOT EXISTS`; rollback drops only the new tables/columns after sessions are revoked and a backup is verified.

The PIN verifier uses salted `hashlib.scrypt` with an encoded cost/parameter format. PIN discovery uses an HMAC-SHA256 lookup keyed by an HCM-only secret file. The lookup secret is never committed, synchronized, or returned. Rotating it requires an administrator-controlled re-enrollment/reindex operation; old lookup keys are not retained for authentication.

## Security and migration risks

- Six-digit PINs require device-scoped throttling, global throttling, progressive backoff, and audit events; an HMAC lookup is not itself a verifier.
- HCM must fail closed if the lookup secret or session database is unavailable.
- Background polling must not refresh elevated idle expiry; only unlock, authenticated user interaction, and accepted mutating command requests refresh it.
- API error responses must not distinguish nonexistent users from disabled users or incorrect PINs.
- No PIN, verifier, lookup value, device token, or session token may enter ordinary logs, module snapshots, diagnostics, or backups without existing secret protections.
- Production transport must be TLS-protected or otherwise authenticated; the implementation does not authorize plaintext PIN submission across the control VLAN.
- Migration execution remains a separate approved deployment step. This development change does not contact or modify any live database.

## Decision

The schema is sufficiently understood to proceed. The implementation will use the existing PostgreSQL/auth/session architecture, add only the touchscreen-specific tables and user-profile fields, preserve web authentication, and keep production PIN authentication explicitly separate from the simulated preview.

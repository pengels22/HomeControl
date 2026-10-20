# Integration configuration and authentication

Migration `010_integration_configuration.sql` adds non-secret provider config,
schema/flow metadata, credential references, encrypted credential rows, and
single-use OAuth state. Existing provider/device/entity/service identities are
preserved.

Credential values are encrypted with Fernet using the externally supplied
`HCM_INTEGRATION_SECRET_KEY` or the administrator-managed
`HCM_INTEGRATION_SECRET_KEY_FILE`. There is no development fallback key. The
database stores ciphertext and a reference only. Normal inspection, status,
diagnostics, audit rows, and frontend responses never contain plaintext or the
reference UUID. Replacing a credential revokes the previous row. Credential
files and environment values remain deployment secrets and must not be committed.

Providers expose JSON schema and config-flow metadata so the UI can render a
generic setup form. The current internal mock demonstrates host/port config and
an API-key flow. Validation errors are reduced to safe messages. Configuration,
enable/disable, reload, and removal require `ADMIN`; `READONLY` can inspect only.
Mutation actions write sanitized management-audit events and never actuate
physical outputs.

`oauth.py` provides provider-neutral state creation/consumption, injected code
exchange, refresh, and encrypted token storage. `webhooks.py` provides bounded
payload, HMAC, rate, nonce replay, ownership, and normalized event hooks. No
real third-party provider is implemented here, and no external HTTP request is
made in CI.

The Settings page exposes the authenticated Integrations panel. It shows status,
configuration, credential presence, last success, and sanitized errors. Secrets
are write-only; reconfiguration may replace a credential but cannot retrieve it.

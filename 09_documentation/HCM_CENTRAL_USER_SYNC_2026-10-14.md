# HCM Central User Synchronization

HCM remains the authoritative user database. After a central user creation,
password change, password reset, or role change, HCM sends an identity-bound
snapshot over the existing authenticated module control session. Reconnecting
modules receive the current snapshot during the normal configuration exchange.

Snapshots contain usernames, enabled state, ADMIN/READONLY role, and the
existing PBKDF2-SHA256 password verifier and parameters. They never contain
plaintext passwords, sessions, tokens, private keys, or GitHub credentials.
The snapshot includes the target permanent device ID, a content revision, an
issue sequence, and an integrity checksum. Modules validate all of these before
atomically replacing their central-user cache. Older issue sequences, wrong
device IDs, malformed roles, unsupported verifier formats, and checksum
mismatches are rejected.

Offline verification necessarily increases password-guessing exposure because
an enrolled module holds a password verifier. HCM's existing PBKDF2 settings
are preserved; this change does not weaken central hashing. Modules retain
login throttling, expiry, CSRF protection, restrictive cookies, and audit
logging. Central revocations and role changes cannot affect an isolated module
until its authenticated session reconnects; the latest accepted snapshot is
used until then.

The pre-existing LAB1 local bootstrap is retained separately. When its
username would collide with a synchronized central username, the preserved
credential is explicitly renamed with the `recovery:` prefix and the protected
bootstrap file is updated. It is not a second central user directory and must
be invalidated through the approved recovery procedure after enrollment is
confirmed.

LAB1 remains permanently identified as `2ccf675d3414`, role `LCM`, simulation
enabled, physical outputs disabled, and has no logical bindings. User sync does
not operate outputs or change module role, bindings, configuration CSV
reconciliation, or life-safety behavior.

Account disable/delete endpoints were not present in the existing HCM Users
API; no new destructive account operation was introduced. Existing password
and role changes revoke HCM sessions and propagate through the same snapshot
path.

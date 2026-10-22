# ACM configuration backups

`config-schema.json` is a non-secret export shape for areas, channel/output
configuration, keypad records, and timing defaults. Never commit live PIN
plaintext, salts, derived hashes, session secrets, or transport credentials.
Credential material remains in device NVS and must be re-provisioned after a
public-repository configuration restore.

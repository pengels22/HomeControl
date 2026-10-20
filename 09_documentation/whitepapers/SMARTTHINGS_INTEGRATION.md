# SmartThings Integration

SmartThings is an instance-scoped HCM provider using SmartThings OAuth. Client
settings are entered through the integration configuration flow; access and
refresh tokens are encrypted in the existing credential store. No token or
client secret is returned by the API or diagnostics.

Each connected instance discovers devices through the SmartThings cloud API and
registers them with the generic HCM device/entity registry. SmartThings device
IDs are external identities, so rediscovery and renaming preserve the HCM
logical device and entity records. Devices missing from a later discovery are
marked unavailable and are retained for reappearance. HCM room assignments are
never overwritten.

Mapped capabilities include switch, level, temperature, humidity, contact,
motion, presence, battery, and washer/dryer operating and machine state.
Unknown capabilities remain represented in provider diagnostics and do not
become arbitrary commands. Switch entities expose the normal HCM
`switch.turn_on` and `switch.turn_off` services with target ownership checks.

State synchronization uses bounded SmartThings API requests and normalizes
availability and state through HCM. Webhook admission uses the shared bounded
and replay-protected webhook guard before state synchronization. SmartThings
devices are convenience integrations and never participate in HCM fire,
life-safety, HVAC safety, or physical-output authority.

The current provider uses discovery polling and the shared webhook admission
primitive. Provider subscriptions, richer capability-specific commands, and
provider-specific signature verification beyond the configured HCM webhook
secret remain follow-up work.

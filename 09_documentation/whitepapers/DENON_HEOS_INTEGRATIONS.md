# Denon AVR and HEOS Integrations

Denon AVR and HEOS are local network providers. Each configured instance uses
the generic integration instance, device, entity, service, and event models;
there are no provider-specific tables or cloud credentials. Hosts and ports
are user-configurable and no LAN address is hard-coded.

Denon AVR uses the receiver's documented ASCII control protocol (normally TCP
23). One stable logical media device and one `media_player` entity are created
per instance. Power, normalized volume (`0.0`–`1.0`), mute, source, source list,
availability, and local state notifications are normalized. Services include
turn on/off, volume set/up/down, mute/unmute, and source selection. Main-zone
support is implemented; secondary zones are deferred.

HEOS uses the local CLI protocol (normally TCP 1255). Players are discovered
from the configured host and retain their HEOS player ID as the provider
external identity. Each player is an HCM media device/entity with playback,
volume, mute, source, title, artist, album, and availability state. Play,
pause, stop, next, previous, volume, and mute services are registered.
Player groups are retained as diagnostic/provider state; group commands are
deferred.

Both providers use bounded socket timeouts, reconnect backoff, instance-scoped
service ownership, and stable registry identities across reconnects and
configuration reloads. They have no authority over HCM physical outputs,
HVAC, commissioning, heartbeat, or life-safety behavior.

CI uses fake local transports only. The providers are software-tested but have
not been live-verified against a physical Denon AVR or HEOS system.

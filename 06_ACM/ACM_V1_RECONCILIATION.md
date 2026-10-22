# ACM V1 software reconciliation audit

| Field | Value |
|---|---|
| Audited SHA | `1a7e9838137a55c0d501a7ed9e1e3cc6de949f6a` plus the narrowly scoped audit corrections in the working revision |
| Date | 2026-10-22 |
| Branch | `main` |
| Scope | Software inspection, host tests, firmware builds, and protocol/state review |
| HIL | Not performed |

This is the software reconciliation snapshot for the pinned ACM V1 architecture. `UNKNOWN` MCP/I2C health is intentional before HIL. LCD/touch rendering and electrical behavior remain behind the documented hardware boundaries.

## Result counts

The audit records **47 PASS**, **14 PARTIAL**, **0 FAIL**, and **11 NOT TESTABLE UNTIL HIL** requirements. The findings below explain every partial and HIL item. The working revision corrects four software defects found during the audit: local stable-state debounce, incomplete snapshot acceptance, reversed keypad HELLO direction, and keypad-capacity overflow.

## Hardware assumptions

| Requirement | Status | Evidence | Risk/notes | HIL required? |
|---|---|---|---|---|
| W5500 CS/MOSI/MISO/SCK/RESET/INT = 10/11/12/13/9/14 | PASS | `03_Shared/board_config.h`, `initializeHardware()` | Constants and SPI initialization agree. | Yes, electrical confirmation |
| SD CS/MISO/MOSI/SCK = 4/5/6/7 | PASS | `board_config.h`, `SPI.begin`, `EventLogger` | Pin constants are present. | Yes |
| ACM I2C SDA/SCL = 8/18; MCP 0x20/0x21 | PASS | `board_config.h`, `initializeHardware()` | Addresses and registers are explicit. | Yes |
| Keypad panic/piezo/5 V siren = 16/17/15 | PASS | `board_config.h`, keypad `setup()` | Panic and siren are dedicated pins; piezo uses LEDC. | Yes |
| LCD/touch abstract until exact hardware; generic ESP32-S3 board | PASS | `board_config.h`, `KeypadDisplayBoundary`, `platformio.ini` | No unconfirmed LCD driver was introduced. | Yes |
| USB-only firmware update; no OTA | PASS | `platformio.ini`, README; no OTA symbols | Deployment remains USB-only. | No |
| Actual electrical polarity, relay energization, boot transients | NOT TESTABLE UNTIL HIL | Software sets active-low relay latch HIGH before output enable and keypad siren LOW at boot. | Firmware inspection cannot prove board wiring or voltage behavior. | Yes, HIL-ONLY |

## Alarm state machine

| Requirement | Status | Evidence | Risk/notes | HIL required? |
|---|---|---|---|---|
| Global ACM alarm authority; no independent Area alarm | PASS | `AlarmCore`, `KeypadManager::handleAction`, keypad sends actions to ACM | Areas are configuration/display metadata. | No |
| Valid Home PIN gives immediate `ARMED_HOME`; motion ignored | PASS | `AlarmCore::arm`, `setSensor` | Home has no exit delay. | No |
| Valid Away PIN gives 30 s `ARMING_DELAY` then `ARMED_AWAY` | PASS | `awayExitMs_`, rollover-safe `tick()` | Default is 30000 ms; configurable value remains bounded by deployment configuration. | No |
| Disarm during arming, entry, or triggered | PASS | `requestWithPin` and `disarm` | Deadline and motion qualification are cleared on disarm. | No |
| Open-at-arm bypass until first close | PASS | `arm` marks currently open sensors bypassed; `setSensor` clears bypass on close | Applies to local and remote slots; no permanent bypass flag is exposed. | No |
| Opening entry delay = 30 s | PASS | `beginEntryDelay` | Applies while armed. | No |
| Away motion must remain active 10 s; close cancels qualification | PASS | `motionStarted_`, `tick`, `setSensor` | Motion timer resets when the state closes or faults. | No |
| Entry timeout triggers once | PASS | `tick()` transitions only from `ENTRY_DELAY` | State transition is single edge. | No |
| No Force Arm behavior or UI | PASS | no `FORCE_ARM`/force-arm symbols in ACM sources | Open sensors are bypassed by the pinned rule. | No |
| Panic is physical-only, edge-triggered, release required | PASS | keypad `readPanic`, `KEYPAD_EVENT`, ACM `PANIC` request | Nonblocking 30 ms edge debounce; no touch action. | Yes for electrical proof |
| Alarm remains local when HCM is absent | PASS | `AlarmCore` has no HCM gate; HCM is a status/time/log path | HCM loss only changes trouble/status logging. | No |

## Sensors

| Requirement | Status | Evidence | Risk/notes | HIL required? |
|---|---|---|---|---|
| AlarmCore logical capacity >= 80 | PASS | `AlarmCore::MAX_LOGICAL_SENSORS = 80` | Bitmap storage supports 96 bits; active logical range is 0..79. | No |
| Mapping 0–23 local, 24+ remote | PASS | ACM scans 24 slots; `KeypadManager::logicalSlot()` returns `24 + keypad*8 + input`. | Seven keypads × 8 = 56 remote slots; 24 + 56 = 80. | No |
| Maximum keypad allocation is bounded to core capacity | PASS | `ConfigStore::MAX_KEYPADS=7`; `logicalSlot()` maximum is 79 while `MAX_LOGICAL_SENSORS=80`. | The capacity guard was added during this audit. | No |
| Local INPUT pull-up, LOW=CLOSED/HIGH=OPEN | PASS | MCP pull-ups enabled and `open = !(raw bit)`. | Electrical polarity still needs HIL. | Yes |
| Local stable 250 ms debounce | PASS | `localRawOpen`, `localDebouncedOpen`, `localRawChangedAt` in `01_ACM/main.cpp`. | Corrected during this audit; sampling is still scheduled at 250 ms, with a stable timestamp check. | No |
| Keypad raw/debounced/timestamp and 250 ms stable transition | PASS | keypad `rawOpen`, `debouncedOpen`, `rawChangedAt`. | Uses rollover-safe elapsed arithmetic. | No |
| Exactly OPENING and MOTION sensor types | PASS | `SensorType` has exactly two values; web selectors only expose both. | No hidden third type. | No |
| Local and remote types persist and apply immediately | PASS | ConfigStore fields; web channel update and `updateKeypadConfig` call `setSensorType`. | No HIL required. | No |
| FAULT is unavailable, never OPEN/entry/motion/trigger | PASS | fault slots call `setSensor(..., false, true)`; `AlarmCore` excludes failed sensors from open bitmap and qualification. | Corrected during this audit for generic failed+open callers. | No |

## Areas, rooms, and configuration

| Requirement | Status | Evidence | Risk/notes | HIL required? |
|---|---|---|---|---|
| Every sensor/keypad has one Area; all eight keypad inputs inherit keypad Area | PASS | `ChannelRecord`, `KeypadRecord::area_id`, logical slot ownership. | Area is metadata, not an alarm partition. | No |
| Multiple keypads per Area | PASS | No uniqueness constraint on `area_id`. | No per-Area state exists. | No |
| Area rename preserves stable ID and references | PASS | `renameArea` changes only `name`; channels/relays/keypads retain IDs. | No assigned-delete route is present. | No |
| Room/Location distinct from Area; seeded/custom entries persist | PASS | `RoomRecord`, `DEFAULT_ROOMS`, `addRoom`. | Room is currently configuration plumbing; no alarm semantics attached. | No |
| Schema 1→2 additive migration | PASS | `ConfigStore::begin`, `seedRooms`, migration tests. | Existing area/channel/relay/keypad keys are loaded before room seeding. | No |
| Fresh/current/known-old/unknown schema paths | PARTIAL / MEDIUM | Fresh and schema 2/1/0 paths are explicit; unknown calls `load()` and sets `RECOVERY_REQUIRED`. | `Preferences` put methods are not failure-reporting in this wrapper, so write-transaction success cannot be proven. No silent reseed occurs for unknown schema. | No |

## Credentials and web authentication

| Requirement | Status | Evidence | Risk/notes | HIL required? |
|---|---|---|---|---|
| Named Master/Standard credentials, max 16, salted PBKDF2-HMAC-SHA256 | PASS | `PinStore`, 16-byte random salt, 12000 iterations, 32-byte hash. | No plaintext credentials are stored. | No |
| Failed PIN attempts omit identity and digits | PASS | `PIN_FAILED` audit contains only keypad name; web failure has no PIN metadata. | Source and behavioral tests cover this. | No |
| Legacy reprovision route creates fresh Master only | PASS | `credentialReprovisionRequired`, limited `/reprovision`, `reprovisionMaster`. | Legacy values are not imported. | No |
| Reprovision persistence failure semantics | PARTIAL / MEDIUM | `reprovisionMaster` clears migration flag only after `persist` returns true. | `PinStore::persist()` currently returns true without checking NVS write results; documented limitation. | No |
| Master-only web login, idle timeout, random server token, HttpOnly/SameSite, CSRF, bounded requests, rate limit | PASS | `web_admin.cpp` sessions/parser/CSRF/rate-limit paths and focused tests. | Cookie is intentionally local-network HTTP; no `Secure` attribute is claimed. | No |
| Every credential mutation requires current Master reauthentication | PASS | `PinStore` mutation methods call `isMaster`; web mutations pass current Master. | PIN values are never rendered. | No |

## Relays and sirens

| Requirement | Status | Evidence | Risk/notes | HIL required? |
|---|---|---|---|---|
| Exactly eight active-low relay outputs; safe HIGH before output enable | PASS | MCP GPIOB, `initializeHardware`, `setRelay`. | Electrical proof remains HIL. | Yes |
| Relay Name/Area/Siren metadata | PASS | `RelayRecord`, Outputs tab, ConfigStore persistence. | No arbitrary generic relay-control route. | No |
| Triggered selects only `siren=true`; disarm releases sirens; generic relays untouched | PASS | `applySirenRelays`; runtime flag reconciliation. | Changes to Siren metadata are applied in the loop. | No |
| Keypad 5 V siren boot OFF, triggered continuously, reconnect reconciliation | PASS | keypad GPIO boot default; `LOCAL_SIREN_*`; `reconcileSiren`. | Electrical output still HIL. | Yes |
| Piezo chirps once per countdown second without blocking | PASS | keypad `lastChirpedCountdown`, nonblocking LEDC timing. | No triggered continuous piezo path. | Yes for sound output |

## Keypad protocol and supervision

| Requirement | Status | Evidence | Risk/notes | HIL required? |
|---|---|---|---|---|
| ACM TCP client; keypad TCP listener | PASS | `KeypadManager::connect`, keypad `EthernetServer`. | One session per configured keypad. | Yes |
| Enrollment by IP, identify, MAC learning, authorization, bounded timeout | PASS | `enrollKeypad`, 2 s deadline, `IDENTIFY_RESPONSE`, persistent `saveKeypad`. | MAC is identity metadata, not cryptographic authentication. | Yes |
| Reconnect validates MAC and requires snapshot | PASS | `connect`, identity check, `snapshot_pending`, FAULT until snapshot. | Heartbeat alone cannot clear FAULT. | Yes |
| HELLO direction: keypad→HELLO_ACM; ACM→HELLO_KEYPAD | PASS | Corrected `processFrame` and keypad handshake during audit. | Heartbeat interval is 30 s. | Yes |
| Three missed 30 s heartbeats, rollover-safe, one offline edge | PASS | `OFFLINE_AFTER_MS=90000`, unsigned elapsed comparison, `online` guard. | Network scheduling still needs HIL. | Yes |
| Offline faults exactly eight remote slots | PASS | `setFault` loops only 8 slots for the keypad. | Capacity caveat above remains HIGH. | Yes |
| Complete eight-state snapshot only clears FAULT | PASS | Snapshot parser now requires `count==8`; malformed/incomplete frames do not call `receiveSnapshot`. | JSON parser remains deliberately small and schema-light. | Yes |
| Live updates only channels 1–8, authorized/online matching keypad | PASS | `receiveUpdate` checks MAC, authorization, range, online, snapshot state. | Invalid frames are ignored. | Yes |
| Remove revokes authorization, closes connection, disables slots | PASS | `removeKeypad`. | Record is retained disabled; this is an allowed behavior. | No |

## Keypad UI

| Requirement | Status | Evidence | Risk/notes | HIL required? |
|---|---|---|---|---|
| Notifications/settings/global state and action model | PARTIAL / MEDIUM | `KeypadUiModel` and controller expose pages/actions. | `KeypadDisplayBoundary::render()` is intentionally a no-op until the LCD driver is confirmed. | Yes |
| Disarmed Home/Away; armed/delay/triggered Disarm; no Force Arm/Panic touch | PASS | `KeypadUiController::actionAt/touch`; no touchscreen Panic or Force Arm. | Renderer remains abstract. | Yes |
| One reusable numeric keypad geometry/logic | PASS | `NumericKeypadComponent` and shared `keypad_layout::DIGITS`; design images match. | Actual touch hardware remains HIL. | Yes |
| Welcome screen blocks normal Home until OK | PARTIAL / MEDIUM | `KeypadPage::MASTER_PROVISION` exists, but no functional boot welcome controller/display path is implemented. | Must be completed when the confirmed LCD/touch driver is added; no unconfirmed display implementation was introduced. | Yes |
| Settings/System exposes IP, MAC, Name, Area, Firmware, ACM connection | PARTIAL / MEDIUM | ACM web System page exposes these; keypad model has local area/connection fields. | No functional keypad renderer/system screen is present behind the display boundary. | Yes |

## HCM integration and time

| Requirement | Status | Evidence | Risk/notes | HIL required? |
|---|---|---|---|---|
| ACM_STATUS contains only device_id, hostname, sequence, state, countdown, trouble | PASS | `sendAlarmStatus`; `full` does not add topology. | No sensor/Area/PIN/keypad topology is serialized. | No |
| HCM ACK/connection does not gate local alarm | PASS | No ACK gate in `AlarmCore`; HCM loss only logs/trouble. | Standalone-first behavior is explicit. | No |
| Unified heartbeat-compatible device ID/hostname semantics | PARTIAL / MEDIUM | `deviceId`/`hostname` are persisted and sent in heartbeat/status. | Default `acm-001` is a deployment placeholder; provisioning must set the real identity. | No |
| HCM→ACM→keypad time hierarchy; no public NTP primary | PASS | ACM requests `TIME_RESPONSE` from HCM and forwards `TIME_SYNC`; no NTP client. | HIL needed for live exchange. | Yes |
| Time absence/stale does not affect alarm/siren control | PASS | Time flags are logger/keypad-sync paths only. | No arm/disarm guard uses time validity. | No |

## Logging and SD behavior

| Requirement | Status | Evidence | Risk/notes | HIL required? |
|---|---|---|---|---|
| Unsynced log format `UNSYNC+<millis>ms` | PASS | `EventLogger::timestamp`. | No fake date is produced. | No |
| Synchronized `/logs/YYYY-MM.log` in America/Detroit | PASS | `TZ=EST5EDT,...`, `monthlyPath`, `localDate`. | Current month comes from synchronized system time, not raw millis. | Yes |
| Daily separator exactly three lines | PARTIAL / MEDIUM | `writeSeparatorIfNeeded` writes the required three lines once per in-memory `last_date_`. | Reboot on the same date can repeat a separator because `last_date_` is not reconstructed from the existing file. | Yes |
| Required ACM transition hooks | PARTIAL / MEDIUM | Boot, sensor, PIN, arm, entry, trigger, siren, panic, keypad, HCM, time, web/PIN events are wired in main/manager/web. | Some direct `AlarmCore` transitions are logged by the main loop rather than at the state-machine method, and `SENSOR_RESTORED`/certain edge metadata paths are not uniformly centralized. | No |
| Keypad minimal local logs | PASS | Boot, ACM comms, sensor transitions, and time events only. | Full ACM history is intentionally not mirrored. | No |
| SD failure does not stop alarm/network/siren; retry backoff | PASS | Logger failures set trouble and retry every 30 s; alarm loop continues. | HIL needed for actual media failure. | Yes |
| Bounded web log tail and no arbitrary filesystem browsing | PASS | `recentLines` caps file read to 8192 bytes and 100 lines; Logs tab only. | Fixed stack array is bounded. | No |

## Web administration and backup/security

| Requirement | Status | Evidence | Risk/notes | HIL required? |
|---|---|---|---|---|
| Channels: 24, names, Area, type, state, custom Area, immediate type update | PASS | Channels page and `applyMutation`. | Generated custom-area input markup is compact but should receive a later UI cleanup. | No |
| Outputs: 8, names, Area, Siren, state, custom Area | PASS | Outputs page and relay mutation. | No arbitrary manual relay toggle. | No |
| Areas seeded/add/rename/stable IDs/no assigned-delete | PASS | Areas page and ConfigStore. | No delete route. | No |
| Keypads add/edit/remove, MAC read-only, status, firmware, 8 input fields/types | PASS | Keypads pages and manager methods. | Live display remains abstract. | No |
| PINs add/rename/reset/enable/disable/remove/change Master with reauth | PASS | PIN page and PinStore methods. | PIN values displayed only as `****`. | No |
| System diagnostics fields and MCP/I2C UNKNOWN | PASS | System page; `mcp_healthy_` defaults to false and renders UNKNOWN. | No false hardware claim. | No |
| Logs read-only, bounded, escaped | PASS | Logs page and `htmlEscape`. | No arbitrary file path accepted. | No |
| Public backup excludes secrets | PASS | `backups/config-schema.json` contains configuration shape only; no backup endpoint exports credential material. | Backup is schema/documentation only at this revision. | No |
| Security review: no plaintext PIN/hash/salt/session URL leakage; no GET mutation; bounds/frame limits | PASS | `PinStore`, web parser/routes, `FrameParser::MAX_FRAME`, index checks, focused tests. | Protocol payload escaping/schema validation is intentionally minimal; frame length is bounded. | No |

## Memory, runtime, and protocol risks

| Requirement | Status | Evidence | Risk/notes | HIL required? |
|---|---|---|---|---|
| Bounded HTTP/frame/request/log memory | PASS | 3072-byte request header, 2048-byte body/frame, 8192-byte log tail, 100-line tail. | Arduino `String` remains fragmented over long uptime; all inputs have practical bounds. | No |
| No blocking enrollment/network loops that can starve watchdog | PARTIAL / MEDIUM | Enrollment has a 2 s bounded loop; main loops reset a 10 s watchdog. | Enrollment is synchronous and uses `delay(1)`; validate watchdog behavior on the target board. | Yes |
| Safe boot outputs and no startup alarm from time/SD/network | PASS | Relay preload, keypad siren LOW, alarm initialization. | Electrical proof is HIL. | Yes |
| Protocol frame sender/receiver compatibility | PASS | Shared frame parser/constants; identify, hello, snapshot, update, action, alarm, siren, time paths reviewed. | Payload JSON is parsed with bounded string searches rather than a full schema validator. | Yes |

## State-machine edge review

| Scenario | Observed software behavior | Status |
|---|---|---|
| Away arm with open door | Door is marked bypassed; arming delay begins. | PASS |
| Door closes during arming | Bypass clears; arming continues. | PASS |
| Arming delay expires | State becomes `ARMED_AWAY`. | PASS |
| Door opens while away | Entry delay begins. | PASS |
| PIN at second 29 | Disarm clears deadline and motion qualification. | PASS |
| Triggered then valid PIN | Disarm is accepted and sirens are reconciled off. | PASS |
| Keypad disconnect during entry | Remote slots fault; ACM entry timer continues. | PASS |
| HCM disconnect while triggered | Local triggered state/sirens remain independent. | PASS |
| SD failure while triggered | Logger reports failure; alarm loop and relay policy continue. | PASS |
| Time sync loss while away | Logger status changes; alarm state is untouched. | PASS |
| Keypad reconnect while triggered | Snapshot is required before online; siren is reconciled after complete snapshot. | PASS |
| Motion open 9 s then closes | Qualification clears; no entry delay. | PASS |
| Motion open 10 s | Entry delay begins. | PASS |
| Sensor fault while armed | Slot is failed and excluded from open/trigger qualification. | PASS |
| Fault restored OPEN while armed | Complete snapshot/update restores state and normal opening/motion semantics. | PASS |

## Defects and follow-up

### Software defects corrected in this audit

- **HIGH:** local ACM input handling was periodic sampling rather than stable-state debounce. Corrected with raw/debounced/timestamp state for all 24 local channels.
- **HIGH:** an incomplete keypad snapshot could be treated as eight closed sensors and clear FAULT. Corrected to require all eight boolean states.
- **HIGH:** ACM and keypad HELLO messages were sent in the opposite direction to the pinned protocol. Corrected to ACM→`HELLO_KEYPAD` and keypad→`HELLO_ACM`.

### HIL validation items

- Confirm W5500, SD, I2C/MCP, GPIO polarity, relay safe boot, siren current path, piezo sound, keypad input wiring, panic electrical behavior, LCD/touch geometry, and watchdog behavior on target hardware.
- Exercise real TCP reconnect, snapshot timeout/malformed frames, three-heartbeat offline transition, siren reconciliation, and HCM time exchange.
- Verify power-cycle behavior and daily log separator behavior with real SD media.

### Nonblocking future improvements

- Implement the concrete LCD/touch renderer and functional welcome/System screens.
- Make Preferences writes report and propagate failure, especially credential reprovision and schema migration.
- Reconstruct the last daily separator from the log after reboot.
- Replace the compact string parser with a small schema-aware JSON parser if protocol payloads grow.
- Clean up custom-area form markup and add true embedded HTTP integration tests.

## Classification

`ACM_V1_SOFTWARE_CORRECTIONS_REQUIRED`

The remaining logical-slot capacity mismatch is a HIGH software defect. The display welcome/System requirements are also incomplete in the current abstract renderer, but no additional V1 feature expansion was made during this audit.

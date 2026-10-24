# Pass 8 production integration gap matrix

| Area | Status | Evidence / remaining boundary |
|---|---|---|
| PostgreSQL PNL registration, friendly identity, area and enablement | IMPLEMENTED | Migration 029 and `/api/v1/pnl-production/admin/devices` provide transactional registration and administration. |
| Credential rotation and revocation | IMPLEMENTED | Per-panel random bearer tokens, SHA-256 hashes, generation audit, and disabled/revoked checks. Tokens are returned only at registration/rotation. |
| Area-aware catalog | IMPLEMENTED | Production panel config/state resolve existing HCM entities and retain logical names; no hardware addresses are exposed. |
| Dashboard assignment precedence | IMPLEMENTED | Panel assignment, area assignment, shared published dashboard, then compiled local fallback. Partial unique indexes prevent ambiguous primary assignments. |
| Panel dashboard delivery | IMPLEMENTED | Authenticated config endpoint, published-only layouts, compiler validation, SHA conditional retrieval, area context and catalog. |
| Live state delivery | PARTIAL | Bounded authenticated event stream and resync snapshot are implemented; event publication hooks for every existing HCM state producer remain integration work. |
| Commands and durable deduplication | IMPLEMENTED | Authenticated command endpoint, capability checks, request ledger, expiry, duplicate responses, and existing `command_logical` authority. Physical confirmation remains distinct. |
| Occupancy events | IMPLEMENTED | Authenticated ordered event endpoint with event-key deduplication and durable storage. |
| Sonic policy and acknowledgements | IMPLEMENTED | Persistent monotonic policy, admin controls, panel epoch acknowledgements, and per-panel compliance fields. |
| SVR1 transcription contract | PARTIAL | Session transport remains configurable/simulated; no real ASR or microphone hardware claim. |
| Browser panel management | PARTIAL | Backend operations are production-backed; the existing editor still needs management assignment controls wired into its UI. |
| Hardware TLS, ESP32-P4, W5500, sensors, audio | HARDWARE_BLOCKED | No live deployment or physical validation authorized. |
| SIM/RMC retirement | PARTIAL | Compatibility roles and historical data remain by design; PNL APIs do not depend on them. |

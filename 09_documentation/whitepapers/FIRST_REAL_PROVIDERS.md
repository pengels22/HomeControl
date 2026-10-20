# First real integration providers

The framework now includes factory-registered National Weather Service,
OpenWeatherMap, and OpenAI provider types. They use the existing instance,
credential, device/entity, service, event, and status plumbing; no provider
creates a parallel registry.

NWS accepts user-supplied latitude, longitude, and a bounded polling interval.
It resolves the official `api.weather.gov/points` metadata and then polls the
resolved forecast endpoint with the required User-Agent header. Its normalized
weather entity and temperature sensor retain stable instance ownership. Alerts
and richer alert deduplication remain follow-up work.

OpenWeatherMap accepts user-supplied coordinates, units, interval, and a
write-only encrypted API key. Its current-weather response is mapped to the
shared weather model. NWS and OpenWeatherMap instances can run independently;
one provider failure does not stop its sibling.

OpenAI accepts a write-only encrypted API key and an allowlisted model. It
registers `openai.generate_text` with bounded prompts, response limits, timeout
through the shared HTTP client, sanitized failures, and no physical mutation.
It does not perform chargeable health calls.

The shared provider HTTP client uses async requests, explicit timeouts, bounded
response bodies, injectable transports for tests, and generic sanitized errors.
Polling starts with an immediate update and uses a minimum 60-second interval;
tasks are cancelled on provider stop. Credentials are accessed only through the
instance context and are never returned by normal APIs or diagnostics.

These providers are software-tested with mocked transports only. Real service
credentials and live network validation are intentionally excluded from CI.

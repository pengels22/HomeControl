# Google Calendar and Gmail providers

Google Calendar and Gmail are registered as OAuth provider types through the
shared factory. They use the existing encrypted credential reference, instance
context, bounded HTTP client, device/entity registry, and integration event bus.
No Google client IDs, secrets, tokens, account IDs, calendar IDs, or mailbox IDs
are stored in source.

Calendar instances accept selected calendar IDs and a bounded sync interval. They
normalize timed and all-day events into a stable calendar entity with event ID,
title, description, location, start/end, status, and update metadata. Gmail
instances expose unread count and emit `gmail.message_received` with message and
thread IDs only; message bodies and attachments are never fetched into generic
state or diagnostics.

Both providers poll with per-instance tasks, preserve instance identity, mark
resources unavailable when polling fails, and use the existing credential
accessor for bearer tokens. OAuth start/callback/state validation is shared with
the generic integration OAuth routes. Tests use mocked transports only.

Write operations, Gmail sending, push/watch subscriptions, full history cursor
recovery, and production Google OAuth client onboarding remain future work. Users
must supply OAuth client settings and credentials through the HCM configuration
flow; this repository contains no live Google credentials.

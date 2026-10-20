# Google Calendar and Gmail providers

Google Calendar and Gmail are registered as OAuth provider types through the
shared factory. They use the existing encrypted credential reference, instance
context, bounded HTTP client, device/entity registry, and integration event bus.
No Google client IDs, secrets, tokens, account IDs, calendar IDs, or mailbox IDs
are stored in source.

The setup flow accepts a user-supplied OAuth client ID and stores the client
secret through the encrypted credential store. Provider metadata declares the
read-only Calendar scope (`calendar.readonly`) and Gmail metadata scope
(`gmail.metadata`). The HCM callback URI is supplied to the OAuth start flow
and must be registered in the Google Cloud project before connecting.

Calendar instances accept selected calendar IDs and a bounded sync interval. They
normalize timed and all-day events into a stable calendar entity with event ID,
title, description, location, start/end, status, and update metadata. Gmail
instances expose unread count and emit `gmail.message_received` with message and
thread IDs only; message bodies and attachments are never fetched into generic
state or diagnostics. Calendar lifecycle state is retained in generic instance
sync state, so unchanged responses do not repeat updates and removed events
produce `google_calendar.event_cancelled`. Gmail establishes a first-sync
baseline, stores the returned history ID and seen IDs, and only emits new-message
events after that baseline.

Both providers poll with per-instance tasks, preserve instance identity, mark
resources unavailable when polling fails, and use the existing credential
accessor for bearer tokens. OAuth start/callback/state validation is shared with
the generic integration OAuth routes. Tests use mocked transports only.

Write operations, Gmail sending, and push/watch subscriptions remain future work.
The Gmail adapter uses `history.list` cursors with a durable baseline and bounded
de-duplication set; expired cursors trigger a fresh baseline without replaying
the mailbox. Calendar instances schedule start/end transitions from each event
occurrence ID, cancel and reschedule changed events, and reconstruct pending
transitions after restart. Users must supply OAuth client settings and
credentials through the HCM configuration flow; this repository contains no live
Google credentials.

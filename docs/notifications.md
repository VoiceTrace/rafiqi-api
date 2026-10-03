# Firebase notification operations

Project: `rafiki-1c4d9`. First event: creation of a class lesson-resource
assignment. Updating an existing assignment does not notify again.

## Local setup

Install requirements, then run `alembic upgrade head`.

Required backend settings:

```dotenv
FIREBASE_PROJECT_ID=rafiki-1c4d9
NOTIFICATION_INBOX_ENABLED=true
NOTIFICATION_PUSH_ENABLED=true
NOTIFICATION_TOKEN_KEY=<persistent Fernet encryption key>
NOTIFICATION_WEB_ORIGIN=http://localhost:3000
GOOGLE_APPLICATION_CREDENTIALS=<absolute path outside the repository>
NOTIFICATION_PUSH_LIMIT=10
NOTIFICATION_PUSH_WINDOW_SECONDS=600
```

The API and worker must share the database and encryption key. Keep the key
stable: replacing it without re-encrypting addresses prevents old devices from
receiving notifications. Never commit credentials or print provider addresses.

Start the API normally and run the worker separately:

```text
python -m app.services.notification_worker
```

## Delivery behavior

The business transaction writes one outbox event. The worker expands at most
100 recipients per transaction, creates one inbox entry per eligible student,
and then sends through Firebase. PostgreSQL row locks serialize worker claims
and account-level push-budget reservations. Delivery holds installation/account
locks for a bounded send (25 seconds), preventing concurrent account rebinding.
A crash releases locks and rolls back the claim; retry can repeat a push, so a
stable notification tag is used. This is a deliberate simpler implementation
of recoverable worker claims, rather than committed leases.

Ten distinct notifications reserve push slots per user per rolling ten minutes.
Devices share a slot; retries retain it. A reservation counts attempted delivery,
even when Firebase temporarily fails. Excess notifications remain unread in the
inbox and delivery rows become `suppressed`; they are never sent later.

New jobs are generated only when push is enabled. Turning push back on does not
push historical inbox entries created while disabled. Registrations unseen for
30 days do not receive new jobs. Invalid Firebase registrations are disabled.

The first release uses supported Firebase Installation ID APIs: JS
`register`/`onRegistered`, Python `Message(fid=...)` and `send_each_async`.
Generic localized content is displayed once by the background FCM worker.
Foreground callbacks show a dismissible app alert.

## Deployment

Run the API and worker as separate supervised processes with automatic restart.
Production web origin must use HTTPS. Use workload identity on supported hosts
instead of downloading another JSON key. This local development project is not
an isolated production environment; configure a separate project before launch.

Database cascades remove installations, notifications, and delivery rows when a
user is deleted. History retention is intentionally not automatically purged:
school policy and the retention period must be agreed before production.

Monitor pending outbox/delivery age, failed deliveries, invalid registrations,
worker logs, and process health. `accepted` means Firebase accepted the message,
not that the browser displayed it or that the user read it.

Local HTTP development omits `WebpushFCMOptions.link`, which Firebase only
accepts for HTTPS URLs. Foreground alerts still open the inbox. Production must
configure an HTTPS origin to support background notification click navigation.

## Verification

`pytest tests/test_notifications.py` exercises real PostgreSQL in generated
isolated schemas. Each schema is removed at teardown; application records are
untouched. Coverage includes ownership, cutoff behavior, transaction rollback,
deduplication/fanout, destination authorization, registration rebinding, refresh,
retry, and shared-device rate accounting.

Verified locally on 2026-10-03: five notification tests passed; a real teacher
assignment created inbox records and Firebase accepted delivery to the registered
Chrome browser. The browser displayed the foreground alert, and opening the
notification reached the intended lesson and cleared its unread badge. Updating
the same assignment did not create another outbox event. English and Arabic
mobile layouts were checked at 390px, including RTL overflow checks. Background
OS display and production deployment remain separate launch checks.

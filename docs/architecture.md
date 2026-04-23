# Current Architecture

## Runtime

The live product is a temp mail service built around one primary FastAPI app.

- Render hosts the web app and API
- Neon stores mailboxes, messages, and AI extraction data
- Cloudflare Email Routing forwards inbound mail into the Email Worker
- The Cloudflare worker normalizes the message payload and calls `POST /ingest/messages`
- The FastAPI app stores the message, extracts OTP/action data, and serves the inbox UI

## Main Surfaces

### Browser app

- mailbox creation
- unified inbox for the current session
- per-mailbox history
- message detail with plain text / HTML / raw payload
- admin archive protected by `ARCHIVE_ADMIN_TOKEN`

### Desktop widget

- lightweight inbox surface for recent codes
- quick open into the main app
- code copy affordance

### Email ingest

- worker code lives in `workers/email-ingest/`
- provider payloads are normalized before they hit the app
- backend also repairs legacy quoted-printable / mojibake content for old stored mail

## Code Map

- `app/main.py` application bootstrap
- `app/api/tempmail.py` temp mail API
- `app/api/admin_archive.py` admin archive API
- `app/repositories/messages.py` inbox and archive reads
- `app/services/ai_service.py` deterministic + Groq analysis
- `app/services/text_encoding.py` content normalization and repair
- `workers/email-ingest/src/index.ts` Cloudflare worker entrypoint

## Legacy Scope

The repository still contains old Gmail/Telegram standalone assets under `legacy/standalone/`,
but they are not the primary deploy path anymore.

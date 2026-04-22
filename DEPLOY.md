# Deploy Guide

## Current Recommended Deploy Path

For the new tempmail architecture, the preferred deploy target is:

- Render free web service for the FastAPI app
- Neon Postgres for persistence
- Cloudflare for DNS, inbound routing, Turnstile, and edge integration

The repository now includes [render.yaml](/D:/Development/Tempmail/render.yaml:1) for the main web service blueprint.

### Render Web Service

Use these commands:

```bash
pip install -r requirements.txt
uvicorn app.main:create_app --factory --host 0.0.0.0 --port $PORT
```

### Required Render Environment Variables

```env
APP_ENV=prod
LOG_LEVEL=INFO
PUBLIC_MAIL_DOMAIN=mail.example.com
DATABASE_URL=postgresql+psycopg://...
DATABASE_URL_DIRECT=postgresql+psycopg://...
SESSION_SECRET=change-me
INGEST_WEBHOOK_SECRET=change-me
TURNSTILE_SITE_KEY=...
TURNSTILE_SECRET_KEY=...
CLOUDFLARE_API_TOKEN=...
CLOUDFLARE_ACCOUNT_ID=...
CLOUDFLARE_ZONE_ID=...
GROQ_API_KEYS=key1,key2,key3
```

### Current Runtime Surface

The app now exposes the main tempmail API needed for the MVP:

- `POST /mailboxes`
- `GET /mailboxes`
- `GET /inbox`
- `GET /mailboxes/{mailbox_id}/messages`
- `GET /messages/{message_id}`
- `POST /messages/{message_id}/analyze`
- `GET /notifications/latest`
- `POST /ingest/messages`
- `GET /health`

### Cloudflare Ingest Note

The intended next deployment step is:

1. Cloudflare receives inbound email.
2. Cloudflare resolves the target mailbox address.
3. Cloudflare sends normalized payloads into `POST /ingest/messages`.
4. The app stores the message, performs deterministic extraction, and returns a notification-ready payload.

The Cloudflare Worker implementation now lives in:

- [workers/email-ingest/src/index.ts](/D:/Development/Tempmail/workers/email-ingest/src/index.ts:1)
- [workers/email-ingest/wrangler.jsonc](/D:/Development/Tempmail/workers/email-ingest/wrangler.jsonc:1)

Before binding the Worker to a live catch-all route:

```bash
cd workers/email-ingest
npm install
npm run typecheck
npx wrangler deploy --dry-run
npx wrangler secret put INGEST_WEBHOOK_SECRET
npx wrangler deploy
```

Do not bind the Email Routing catch-all until `APP_INGEST_URL` points to the real Render URL.

## Legacy Standalone Path

## What Is Required

Copy these files to the target server:

- the whole project directory
- `.env`
- `google_client_secret.json`
- `google_token.json`
- optional `data/app.db` if you want to keep the current state

Do not commit or publish the secret files.

## Recommended Linux Deploy Path

```bash
sudo mkdir -p /srv/mail-telegram-app
sudo rsync -av ./ /srv/mail-telegram-app/
sudo chown -R deploy:deploy /srv/mail-telegram-app
cd /srv/mail-telegram-app
```

## Prepare `.env`

At minimum:

```env
APP_ENV=prod
DATABASE_URL=sqlite:///./data/app.db
GMAIL_CLIENT_SECRET_PATH=./google_client_secret.json
GMAIL_TOKEN_PATH=./google_token.json
GMAIL_POLL_SECONDS=60
DEFAULT_FROM_ALIAS_DOMAIN=example.com
APP_HOST=127.0.0.1
APP_PORT=8787
TELEGRAM_BOT_TOKEN=...
TELEGRAM_WEBHOOK_SECRET=...
ALIAS_API_TOKEN=...
LOG_LEVEL=INFO
```

Relative paths are now resolved against the project root, so the service no longer depends on the process working directory.

## Install As Standalone Services

Run as root on the target server:

```bash
cd /srv/mail-telegram-app
chmod +x scripts/install_on_linux.sh
sudo ./scripts/install_on_linux.sh --app-dir /srv/mail-telegram-app --app-user deploy
```

This will:

- create `.venv`
- install Python dependencies
- install two systemd units
- start the API and worker as standalone services

## Service Names

- `mail-telegram-api.service`
- `mail-telegram-worker.service`

Useful commands:

```bash
sudo systemctl status mail-telegram-api.service
sudo systemctl status mail-telegram-worker.service
sudo journalctl -u mail-telegram-api.service -f
sudo journalctl -u mail-telegram-worker.service -f
curl -fsS http://127.0.0.1:8787/health
```

## Migration Notes

- To preserve aliases, inbox history, and worker cursors, also copy `data/app.db`.
- To start from scratch on a new server, omit `data/app.db` and the app will bootstrap a clean SQLite database.
- The current runtime no longer needs Hermes as a parent process if launched through these systemd units.
